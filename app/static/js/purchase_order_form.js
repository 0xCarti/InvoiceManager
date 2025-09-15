(function () {
    "use strict";

    function toNumber(value) {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : 0;
    }

    function initPurchaseOrderForm(config) {
        const container = config && config.container ? config.container : null;
        if (!container) {
            return;
        }

        const addRowButton = config.addRowButton || null;
        const quickAddButton = config.quickAddButton || null;
        const saveNewItemButton = config.saveNewItemButton || null;
        const newItemModalEl = config.newItemModal || null;
        const searchTimers = new WeakMap();

        let nextIndex = toNumber(
            config.nextIndex !== undefined
                ? config.nextIndex
                : container.dataset.nextIndex
        );
        if (nextIndex < container.querySelectorAll(".item-row").length) {
            nextIndex = container.querySelectorAll(".item-row").length;
        }
        container.dataset.nextIndex = String(nextIndex);

        let newItemModal = null;
        if (newItemModalEl && typeof bootstrap !== "undefined") {
            newItemModal =
                bootstrap.Modal.getInstance(newItemModalEl) ||
                new bootstrap.Modal(newItemModalEl);
        }

        function closeAllSuggestionLists(exceptList) {
            container.querySelectorAll(".suggestion-list").forEach((list) => {
                if (list !== exceptList) {
                    list.classList.add("d-none");
                }
            });
        }

        function clearSuggestions(list) {
            if (list) {
                list.innerHTML = "";
                list.classList.add("d-none");
            }
        }

        function clearUnits(unitSelect) {
            if (unitSelect) {
                unitSelect.innerHTML = "";
                unitSelect.dataset.selected = "";
            }
        }

        function fetchUnits(itemId, unitSelect, selectedUnitId) {
            if (!unitSelect || !itemId) {
                clearUnits(unitSelect);
                return;
            }

            fetch(`/items/${itemId}/units`)
                .then((response) => {
                    if (!response.ok) {
                        throw new Error("Failed to load units");
                    }
                    return response.json();
                })
                .then((data) => {
                    const options = data.units
                        .map((unit) => {
                            const shouldSelect = selectedUnitId
                                ? parseInt(selectedUnitId, 10) === unit.id
                                : unit.receiving_default;
                            const plural = unit.factor !== 1 ? "s" : "";
                            return `
                                <option value="${unit.id}" ${
                                shouldSelect ? "selected" : ""
                            }>
                                    ${unit.name} of ${unit.factor} ${data.base_unit}${plural}
                                </option>
                            `;
                        })
                        .join("");
                    unitSelect.innerHTML = options;
                    unitSelect.dataset.selected = "";
                })
                .catch(() => {
                    clearUnits(unitSelect);
                });
        }

        function createRowElement(index, options = {}) {
            const row = document.createElement("div");
            row.classList.add("row", "g-2", "mt-2", "item-row", "align-items-center");

            const itemCol = document.createElement("div");
            itemCol.classList.add("col", "position-relative");

            const searchInput = document.createElement("input");
            searchInput.type = "text";
            searchInput.name = `items-${index}-item-label`;
            searchInput.classList.add("form-control", "item-search");
            searchInput.placeholder = "Search for an item";
            searchInput.autocomplete = "off";
            if (options.itemName) {
                searchInput.value = options.itemName;
            }
            itemCol.appendChild(searchInput);

            const hiddenInput = document.createElement("input");
            hiddenInput.type = "hidden";
            hiddenInput.name = `items-${index}-item`;
            hiddenInput.classList.add("item-id-field");
            if (options.itemId) {
                hiddenInput.value = options.itemId;
            }
            itemCol.appendChild(hiddenInput);

            const suggestionList = document.createElement("div");
            suggestionList.classList.add(
                "list-group",
                "suggestion-list",
                "d-none",
                "position-absolute",
                "w-100"
            );
            suggestionList.style.zIndex = "1000";
            suggestionList.style.maxHeight = "200px";
            suggestionList.style.overflowY = "auto";
            itemCol.appendChild(suggestionList);

            const unitCol = document.createElement("div");
            unitCol.classList.add("col");
            const unitSelect = document.createElement("select");
            unitSelect.name = `items-${index}-unit`;
            unitSelect.classList.add("form-control", "unit-select");
            unitSelect.dataset.selected = options.unitId ? String(options.unitId) : "";
            unitCol.appendChild(unitSelect);

            const quantityCol = document.createElement("div");
            quantityCol.classList.add("col");
            const quantityInput = document.createElement("input");
            quantityInput.type = "number";
            quantityInput.step = "any";
            quantityInput.name = `items-${index}-quantity`;
            quantityInput.classList.add("form-control", "quantity");
            if (options.quantity !== undefined && options.quantity !== null) {
                quantityInput.value = options.quantity;
            }
            quantityCol.appendChild(quantityInput);

            const removeCol = document.createElement("div");
            removeCol.classList.add("col-auto");
            const removeButton = document.createElement("button");
            removeButton.type = "button";
            removeButton.classList.add("btn", "btn-danger", "remove-item");
            removeButton.textContent = "Remove";
            removeCol.appendChild(removeButton);

            row.append(itemCol, unitCol, quantityCol, removeCol);
            return row;
        }

        function addRow(options = {}) {
            const row = createRowElement(nextIndex, options);
            container.appendChild(row);
            nextIndex += 1;
            container.dataset.nextIndex = String(nextIndex);

            const unitSelect = row.querySelector(".unit-select");
            if (options.itemId) {
                fetchUnits(options.itemId, unitSelect, options.unitId || null);
            }

            if (!options.itemId) {
                const searchInput = row.querySelector(".item-search");
                if (searchInput) {
                    searchInput.focus();
                }
            }

            return row;
        }

        function performSearch(input, term) {
            const row = input.closest(".item-row");
            if (!row) {
                return;
            }
            const suggestionList = row.querySelector(".suggestion-list");
            if (!suggestionList) {
                return;
            }

            fetch(`/items/search?term=${encodeURIComponent(term)}`)
                .then((response) => {
                    if (!response.ok) {
                        throw new Error("Search failed");
                    }
                    return response.json();
                })
                .then((items) => {
                    if (input.value.trim() !== term) {
                        return;
                    }

                    suggestionList.innerHTML = "";
                    if (!items.length) {
                        suggestionList.classList.add("d-none");
                        return;
                    }

                    items.forEach((item) => {
                        const option = document.createElement("button");
                        option.type = "button";
                        option.className =
                            "list-group-item list-group-item-action suggestion-option";
                        option.textContent = item.name;
                        option.dataset.itemId = item.id;
                        option.dataset.itemName = item.name;
                        suggestionList.appendChild(option);
                    });

                    suggestionList.classList.remove("d-none");
                })
                .catch(() => {
                    suggestionList.classList.add("d-none");
                });
        }

        function handleSearchInput(input) {
            const row = input.closest(".item-row");
            if (!row) {
                return;
            }
            const hiddenField = row.querySelector(".item-id-field");
            const unitSelect = row.querySelector(".unit-select");
            const suggestionList = row.querySelector(".suggestion-list");

            if (hiddenField) {
                hiddenField.value = "";
            }
            clearUnits(unitSelect);
            closeAllSuggestionLists(suggestionList);

            const term = input.value.trim();
            if (!term) {
                clearSuggestions(suggestionList);
                return;
            }

            if (searchTimers.has(input)) {
                clearTimeout(searchTimers.get(input));
            }
            const timer = setTimeout(() => {
                performSearch(input, term);
            }, 150);
            searchTimers.set(input, timer);
        }

        function handleSuggestionSelection(option) {
            const row = option.closest(".item-row");
            if (!row) {
                return;
            }

            const hiddenField = row.querySelector(".item-id-field");
            const searchInput = row.querySelector(".item-search");
            const unitSelect = row.querySelector(".unit-select");
            const suggestionList = row.querySelector(".suggestion-list");

            if (hiddenField) {
                hiddenField.value = option.dataset.itemId || "";
            }
            if (searchInput) {
                searchInput.value = option.dataset.itemName || "";
            }
            clearSuggestions(suggestionList);
            fetchUnits(option.dataset.itemId, unitSelect);

            const quantityInput = row.querySelector(".quantity");
            if (quantityInput) {
                quantityInput.focus();
            }
        }

        function handleSearchKeydown(event) {
            const input = event.target;
            const row = input.closest(".item-row");
            if (!row) {
                return;
            }
            const suggestionList = row.querySelector(".suggestion-list");
            if (!suggestionList) {
                return;
            }

            if (event.key === "Enter") {
                const firstOption = suggestionList.querySelector(".suggestion-option");
                if (!suggestionList.classList.contains("d-none") && firstOption) {
                    event.preventDefault();
                    handleSuggestionSelection(firstOption);
                }
            } else if (event.key === "Escape") {
                suggestionList.classList.add("d-none");
            }
        }

        function handleQuantityKeydown(event) {
            if (event.key !== "Tab" || event.shiftKey) {
                return;
            }
            const currentRow = event.target.closest(".item-row");
            if (!currentRow) {
                return;
            }
            const nextRow = currentRow.nextElementSibling;
            if (!nextRow) {
                return;
            }
            const nextQuantity = nextRow.querySelector(".quantity");
            if (nextQuantity) {
                event.preventDefault();
                nextQuantity.focus();
            }
        }

        if (addRowButton) {
            addRowButton.addEventListener("click", (event) => {
                event.preventDefault();
                addRow();
            });
        }

        if (quickAddButton && newItemModal) {
            quickAddButton.addEventListener("click", () => {
                newItemModal.show();
            });
        }

        if (saveNewItemButton) {
            saveNewItemButton.addEventListener("click", () => {
                const nameInput = document.getElementById("new-item-name");
                const glCodeSelect = document.getElementById("new-item-gl-code");
                const baseUnitSelect = document.getElementById("new-item-base-unit");
                const receivingUnitInput = document.getElementById(
                    "new-item-receiving-unit"
                );
                const receivingFactorInput = document.getElementById(
                    "new-item-receiving-factor"
                );
                const transferUnitInput = document.getElementById(
                    "new-item-transfer-unit"
                );
                const transferFactorInput = document.getElementById(
                    "new-item-transfer-factor"
                );
                const csrfTokenInput = document.querySelector(
                    'input[name="csrf_token"]'
                );

                const name = nameInput ? nameInput.value.trim() : "";
                const glCode = glCodeSelect ? glCodeSelect.value : null;
                const baseUnit = baseUnitSelect ? baseUnitSelect.value : null;
                const receivingUnit = receivingUnitInput
                    ? receivingUnitInput.value.trim()
                    : "";
                const receivingFactor = receivingFactorInput
                    ? parseFloat(receivingFactorInput.value) || 0
                    : 0;
                const transferUnit = transferUnitInput
                    ? transferUnitInput.value.trim()
                    : "";
                const transferFactor = transferFactorInput
                    ? parseFloat(transferFactorInput.value) || 0
                    : 0;
                const csrfToken = csrfTokenInput ? csrfTokenInput.value : null;

                if (
                    !name ||
                    !receivingUnit ||
                    !transferUnit ||
                    receivingFactor <= 0 ||
                    transferFactor <= 0
                ) {
                    return;
                }

                fetch("/items/quick_add", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRFToken": csrfToken || "",
                    },
                    body: JSON.stringify({
                        name,
                        purchase_gl_code: glCode,
                        base_unit: baseUnit,
                        receiving_unit: receivingUnit,
                        receiving_factor: receivingFactor,
                        transfer_unit: transferUnit,
                        transfer_factor: transferFactor,
                    }),
                })
                    .then((response) => {
                        if (!response.ok) {
                            throw new Error("Unable to create item");
                        }
                        return response.json();
                    })
                    .then((data) => {
                        if (!data || !data.id) {
                            return;
                        }
                        const row = addRow({
                            itemId: data.id,
                            itemName: data.name,
                        });
                        const unitSelect = row.querySelector(".unit-select");
                        fetchUnits(data.id, unitSelect);
                        const quantityInput = row.querySelector(".quantity");
                        if (quantityInput) {
                            quantityInput.focus();
                        }

                        if (nameInput) {
                            nameInput.value = "";
                        }
                        if (receivingUnitInput) {
                            receivingUnitInput.value = "";
                        }
                        if (receivingFactorInput) {
                            receivingFactorInput.value = "1";
                        }
                        if (transferUnitInput) {
                            transferUnitInput.value = "";
                        }
                        if (transferFactorInput) {
                            transferFactorInput.value = "1";
                        }

                        if (newItemModal) {
                            newItemModal.hide();
                        }
                    })
                    .catch(() => {
                        /* Silent failure keeps UI responsive */
                    });
            });
        }

        container.addEventListener("input", (event) => {
            if (event.target.classList.contains("item-search")) {
                handleSearchInput(event.target);
            }
        });

        container.addEventListener("focusin", (event) => {
            if (event.target.classList.contains("item-search")) {
                const row = event.target.closest(".item-row");
                if (!row) {
                    return;
                }
                const suggestionList = row.querySelector(".suggestion-list");
                if (suggestionList && suggestionList.children.length) {
                    closeAllSuggestionLists(suggestionList);
                    suggestionList.classList.remove("d-none");
                }
            }
        });

        container.addEventListener("keydown", (event) => {
            if (event.target.classList.contains("item-search")) {
                handleSearchKeydown(event);
            } else if (event.target.classList.contains("quantity")) {
                handleQuantityKeydown(event);
            }
        });

        container.addEventListener("click", (event) => {
            if (event.target.classList.contains("remove-item")) {
                event.target.closest(".row").remove();
            } else if (event.target.classList.contains("suggestion-option")) {
                handleSuggestionSelection(event.target);
            }
        });

        document.addEventListener("click", (event) => {
            if (!container.contains(event.target)) {
                closeAllSuggestionLists();
            }
        });

        Array.from(container.querySelectorAll(".item-row")).forEach((row) => {
            const hiddenField = row.querySelector(".item-id-field");
            const unitSelect = row.querySelector(".unit-select");
            const selectedUnit = unitSelect ? unitSelect.dataset.selected : null;
            if (hiddenField && hiddenField.value) {
                fetchUnits(hiddenField.value, unitSelect, selectedUnit || null);
            }
        });

        return {
            addRow,
        };
    }

    window.initPurchaseOrderForm = initPurchaseOrderForm;
})();
