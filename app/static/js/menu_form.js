(function () {
    "use strict";

    function ready(fn) {
        if (document.readyState !== "loading") {
            fn();
        } else {
            document.addEventListener("DOMContentLoaded", fn);
        }
    }

    function toggleStatus(statusEl, message, isError) {
        if (!statusEl) {
            return;
        }
        statusEl.textContent = message;
        statusEl.classList.remove("d-none", "text-danger", "text-success");
        statusEl.classList.add(isError ? "text-danger" : "text-success");
    }

    function clearStatus(statusEl) {
        if (!statusEl) {
            return;
        }
        statusEl.textContent = "";
        statusEl.classList.add("d-none");
        statusEl.classList.remove("text-danger", "text-success");
    }

    ready(function () {
        var productSelect = document.getElementById("product_ids");
        if (!productSelect) {
            return;
        }

        var menuForm = document.getElementById("menu-form");
        var endpoint = null;
        if (menuForm && menuForm.dataset.productsEndpoint) {
            endpoint = menuForm.dataset.productsEndpoint;
        }

        var searchInput = document.getElementById("product-search");
        var clearSearchButton = document.getElementById("product-search-clear");

        function applyProductFilter() {
            if (!searchInput) {
                return;
            }
            var term = searchInput.value.trim().toLowerCase();
            Array.prototype.forEach.call(productSelect.options, function (option) {
                if (!term) {
                    option.hidden = false;
                    return;
                }
                var matches = option.text.toLowerCase().indexOf(term) !== -1;
                option.hidden = !matches;
            });
        }

        if (searchInput) {
            searchInput.addEventListener("input", applyProductFilter);
        }

        if (clearSearchButton) {
            clearSearchButton.addEventListener("click", function () {
                if (!searchInput) {
                    return;
                }
                searchInput.value = "";
                applyProductFilter();
                searchInput.focus();
            });
        }

        var copySelect = document.getElementById("copy-menu-select");
        var copyButton = document.getElementById("copy-menu-button");
        var statusEl = document.getElementById("copy-menu-status");

        if (!endpoint && copySelect && copySelect.dataset.productsEndpoint) {
            endpoint = copySelect.dataset.productsEndpoint;
        }

        function setSelectedProducts(productIds) {
            var idSet = new Set(productIds.map(function (id) {
                return String(id);
            }));
            Array.prototype.forEach.call(productSelect.options, function (option) {
                option.selected = idSet.has(option.value);
            });
            applyProductFilter();
        }

        if (copySelect && copyButton && endpoint) {
            copyButton.addEventListener("click", function () {
                clearStatus(statusEl);
                var selectedMenuId = copySelect.value;
                if (!selectedMenuId) {
                    toggleStatus(statusEl, "Please choose a menu to copy from.", true);
                    return;
                }

                copyButton.disabled = true;
                var originalText = copyButton.textContent;
                copyButton.textContent = "Copying…";

                var url = endpoint + (endpoint.indexOf("?") === -1 ? "?" : "&") + "menu_id=" + encodeURIComponent(selectedMenuId);

                fetch(url, {
                    headers: {
                        Accept: "application/json"
                    }
                })
                    .then(function (response) {
                        if (!response.ok) {
                            throw new Error("Unable to load menu products");
                        }
                        return response.json();
                    })
                    .then(function (data) {
                        if (!data || !Array.isArray(data.product_ids)) {
                            throw new Error("Unexpected response from server");
                        }
                        setSelectedProducts(data.product_ids);
                        toggleStatus(statusEl, "Copied products from " + (data.name || "selected menu") + ".", false);
                    })
                    .catch(function (error) {
                        console.error(error);
                        toggleStatus(statusEl, error.message || "Unable to copy products.", true);
                    })
                    .finally(function () {
                        copyButton.disabled = false;
                        copyButton.textContent = originalText;
                    });
            });
        }

        var quickProductForm = document.getElementById("quick-product-form");
        var quickProductErrors = document.getElementById("quick-product-errors");
        var quickProductFeedback = document.getElementById("quick-product-feedback");
        var quickProductModalEl = document.getElementById("quickProductModal");

        function showQuickProductFeedback(message, isError) {
            if (!quickProductFeedback) {
                return;
            }
            quickProductFeedback.textContent = message;
            quickProductFeedback.classList.remove("d-none", "text-danger", "text-success");
            quickProductFeedback.classList.add(isError ? "text-danger" : "text-success");
        }

        function clearQuickProductFeedback() {
            if (!quickProductFeedback) {
                return;
            }
            quickProductFeedback.textContent = "";
            quickProductFeedback.classList.add("d-none");
            quickProductFeedback.classList.remove("text-danger", "text-success");
        }

        function displayQuickProductErrors(errors) {
            if (!quickProductErrors) {
                return;
            }
            if (!errors) {
                quickProductErrors.innerHTML = "";
                quickProductErrors.classList.add("d-none");
                return;
            }
            var messages = [];
            Object.keys(errors).forEach(function (field) {
                var fieldErrors = errors[field];
                if (Array.isArray(fieldErrors)) {
                    fieldErrors.forEach(function (message) {
                        messages.push(message);
                    });
                }
            });
            if (!messages.length) {
                quickProductErrors.innerHTML = "";
                quickProductErrors.classList.add("d-none");
                return;
            }
            var list = document.createElement("ul");
            list.classList.add("mb-0");
            messages.forEach(function (message) {
                var item = document.createElement("li");
                item.textContent = message;
                list.appendChild(item);
            });
            quickProductErrors.innerHTML = "";
            quickProductErrors.appendChild(list);
            quickProductErrors.classList.remove("d-none");
        }

        function sortProductOptions() {
            var options = Array.prototype.slice.call(productSelect.options);
            options.sort(function (a, b) {
                return a.text.localeCompare(b.text);
            });
            productSelect.innerHTML = "";
            options.forEach(function (option) {
                productSelect.appendChild(option);
            });
        }

        if (quickProductForm) {
            quickProductForm.addEventListener("submit", function (event) {
                event.preventDefault();
                displayQuickProductErrors(null);
                clearQuickProductFeedback();
                var submitButton = quickProductForm.querySelector("button[type='submit'], input[type='submit']");
                if (submitButton) {
                    submitButton.disabled = true;
                    if (submitButton.tagName === "BUTTON") {
                        submitButton.dataset.originalLabel = submitButton.textContent;
                        submitButton.textContent = "Saving…";
                    } else {
                        submitButton.dataset.originalLabel = submitButton.value;
                        submitButton.value = "Saving…";
                    }
                }
                var formData = new FormData(quickProductForm);
                fetch(quickProductForm.getAttribute("action"), {
                    method: "POST",
                    headers: {
                        Accept: "application/json"
                    },
                    body: formData
                })
                    .then(function (response) {
                        if (response.ok) {
                            return response.json();
                        }
                        return response.json().then(function (data) {
                            throw { response: data };
                        }).catch(function () {
                            throw new Error("Unable to create product.");
                        });
                    })
                    .then(function (data) {
                        if (!data || !data.product) {
                            throw new Error("Unexpected response from server.");
                        }
                        var product = data.product;
                        var existing = null;
                        Array.prototype.forEach.call(
                            productSelect.options,
                            function (option) {
                                if (option.value === String(product.id)) {
                                    existing = option;
                                }
                            }
                        );
                        if (!existing) {
                            var newOption = new Option(product.name, product.id, true, true);
                            productSelect.appendChild(newOption);
                            sortProductOptions();
                        } else {
                            existing.selected = true;
                        }
                        applyProductFilter();
                        showQuickProductFeedback(
                            "Created " + product.name + " and added it to this menu.",
                            false
                        );
                        if (quickProductModalEl && window.bootstrap) {
                            var modalInstance = window.bootstrap.Modal.getInstance(quickProductModalEl);
                            if (!modalInstance) {
                                modalInstance = new window.bootstrap.Modal(quickProductModalEl);
                            }
                            modalInstance.hide();
                        }
                        quickProductForm.reset();
                    })
                    .catch(function (error) {
                        if (error && error.response && error.response.errors) {
                            displayQuickProductErrors(error.response.errors);
                        } else {
                            displayQuickProductErrors({ __all__: [error.message || "Unable to create product."] });
                        }
                    })
                    .finally(function () {
                        if (submitButton) {
                            submitButton.disabled = false;
                            var label = submitButton.dataset.originalLabel || "Create Product";
                            if (submitButton.tagName === "BUTTON") {
                                submitButton.textContent = label;
                            } else {
                                submitButton.value = label;
                            }
                            delete submitButton.dataset.originalLabel;
                        }
                    });
            });

            if (quickProductModalEl && window.bootstrap) {
                quickProductModalEl.addEventListener("hidden.bs.modal", function () {
                    displayQuickProductErrors(null);
                    quickProductForm.reset();
                });
            }
        }
    });
})();
