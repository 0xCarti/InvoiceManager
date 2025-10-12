(function () {
    "use strict";

    function initTerminalProductMappings() {
        var containers = document.querySelectorAll("[data-terminal-product-mapping]");
        if (!containers.length) {
            return;
        }

        var datalist = document.getElementById("terminal-product-options");
        var datalistOptions = datalist ? Array.prototype.slice.call(datalist.options) : [];
        var optionByValue = Object.create(null);
        var optionByLowerValue = Object.create(null);
        var optionById = Object.create(null);

        datalistOptions.forEach(function (option) {
            var value = option.value || "";
            var lower = value.toLowerCase();
            var id = option.dataset ? option.dataset.id : option.getAttribute("data-id");
            if (value) {
                optionByValue[value] = option;
                optionByLowerValue[lower] = option;
            }
            if (option.label) {
                optionByLowerValue[option.label.toLowerCase()] = option;
            }
            if (id) {
                optionById[id] = option;
            }
        });

        function resolveOption(rawValue) {
            if (!rawValue) {
                return null;
            }
            var option = optionByValue[rawValue];
            if (option) {
                return option;
            }
            var lower = rawValue.toLowerCase();
            option = optionByLowerValue[lower];
            if (option) {
                return option;
            }
            if (!datalist) {
                return null;
            }
            for (var i = 0; i < datalist.options.length; i += 1) {
                var candidate = datalist.options[i];
                if ((candidate.value || "").toLowerCase() === lower) {
                    return candidate;
                }
                if ((candidate.label || "").toLowerCase() === lower) {
                    return candidate;
                }
            }
            return null;
        }

        function setStatusMessage(target, message, tone) {
            if (!target) {
                return;
            }
            target.textContent = message || "";
            target.classList.remove("text-danger", "text-success", "text-muted");
            if (!message) {
                return;
            }
            switch (tone) {
                case "danger":
                    target.classList.add("text-danger");
                    break;
                case "success":
                    target.classList.add("text-success");
                    break;
                default:
                    target.classList.add("text-muted");
                    break;
            }
        }

        containers.forEach(function (container) {
            var searchInput = container.querySelector("[data-role='product-search-input']");
            var hiddenInput = container.querySelector("[data-role='product-value']");
            if (!hiddenInput) {
                return;
            }
            var statusMessage = container.querySelector("[data-role='selection-status']");
            var errorMessage = container.querySelector("[data-role='selection-error']");
            var skipButton = container.querySelector("[data-action='skip']");
            var createButton = container.querySelector("[data-action='create']");
            var clearButton = container.querySelector("[data-action='clear']");
            var skipValue = container.getAttribute("data-skip-value") || "";
            var createValue = container.getAttribute("data-create-value") || "";

            function hideError() {
                if (errorMessage) {
                    errorMessage.classList.add("d-none");
                }
            }

            function showError() {
                if (errorMessage) {
                    errorMessage.classList.remove("d-none");
                }
            }

            function setActiveButton(activeButton) {
                [skipButton, createButton].forEach(function (button) {
                    if (!button) {
                        return;
                    }
                    if (button === activeButton) {
                        button.classList.add("active");
                    } else {
                        button.classList.remove("active");
                    }
                });
            }

            function linkToOption(option) {
                if (!option || !hiddenInput) {
                    return;
                }
                var optionId = option.dataset ? option.dataset.id : option.getAttribute("data-id");
                if (!optionId) {
                    return;
                }
                hiddenInput.value = optionId;
                setActiveButton(null);
                hideError();
                var display = option.value || option.label || option.textContent || "";
                if (searchInput && display && searchInput.value !== display) {
                    searchInput.value = display;
                }
                setStatusMessage(statusMessage, display ? "Linked to " + display : "", "muted");
            }

            function resetSelectionState() {
                setActiveButton(null);
                hideError();
                if (!searchInput || !searchInput.value.trim()) {
                    setStatusMessage(statusMessage, "", null);
                }
            }

            function initializeState() {
                hideError();
                var value = hiddenInput.value || "";
                if (!value) {
                    resetSelectionState();
                    return;
                }
                if (value === skipValue) {
                    if (searchInput) {
                        searchInput.value = "";
                    }
                    setActiveButton(skipButton);
                    setStatusMessage(statusMessage, "This terminal sale product will be skipped.", "muted");
                    return;
                }
                if (value === createValue) {
                    if (searchInput) {
                        searchInput.value = "";
                    }
                    setActiveButton(createButton);
                    setStatusMessage(statusMessage, "A new product will be created from this sale item.", "muted");
                    return;
                }
                var option = optionById[value];
                if (option) {
                    linkToOption(option);
                } else if (searchInput && searchInput.value) {
                    var inferred = resolveOption(searchInput.value.trim());
                    if (inferred) {
                        linkToOption(inferred);
                    } else {
                        setStatusMessage(statusMessage, "", null);
                    }
                }
            }

            if (clearButton) {
                clearButton.addEventListener("click", function () {
                    if (searchInput) {
                        searchInput.value = "";
                        searchInput.focus();
                    }
                    hiddenInput.value = "";
                    setActiveButton(null);
                    hideError();
                    setStatusMessage(statusMessage, "", null);
                });
            }

            if (skipButton) {
                skipButton.addEventListener("click", function () {
                    hiddenInput.value = skipValue;
                    if (searchInput) {
                        searchInput.value = "";
                    }
                    setActiveButton(skipButton);
                    hideError();
                    setStatusMessage(statusMessage, "This terminal sale product will be skipped.", "muted");
                });
            }

            if (createButton) {
                createButton.addEventListener("click", function () {
                    hiddenInput.value = createValue;
                    if (searchInput) {
                        searchInput.value = "";
                    }
                    setActiveButton(createButton);
                    hideError();
                    setStatusMessage(statusMessage, "A new product will be created from this sale item.", "muted");
                });
            }

            if (searchInput) {
                searchInput.addEventListener("input", function () {
                    hiddenInput.value = "";
                    setActiveButton(null);
                    hideError();
                    if (searchInput.value.trim()) {
                        setStatusMessage(statusMessage, "Select a product from the list to confirm the match.", "muted");
                    } else {
                        setStatusMessage(statusMessage, "", null);
                    }
                });

                searchInput.addEventListener("change", function () {
                    var raw = searchInput.value.trim();
                    if (!raw) {
                        hiddenInput.value = "";
                        resetSelectionState();
                        return;
                    }
                    var option = resolveOption(raw);
                    if (option && (option.dataset ? option.dataset.id : option.getAttribute("data-id"))) {
                        linkToOption(option);
                    } else {
                        hiddenInput.value = "";
                        showError();
                        setStatusMessage(statusMessage, "", null);
                    }
                });
            }

            initializeState();
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initTerminalProductMappings);
    } else {
        initTerminalProductMappings();
    }
})();
