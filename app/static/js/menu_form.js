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
    });
})();
