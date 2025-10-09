(function () {
    function toClassList(classString) {
        return (classString || "")
            .split(/\s+/)
            .map(function (value) {
                return value.trim();
            })
            .filter(function (value) {
                return value.length > 0;
            });
    }

    function syncAltInput(instance) {
        if (!instance || !instance.altInput) {
            return;
        }

        if (instance.selectedDates && instance.selectedDates.length > 0) {
            var formatted = instance.formatDate(
                instance.selectedDates[0],
                instance.config.altFormat
            );
            instance.altInput.value = formatted;
        } else {
            instance.altInput.value = "";
        }
    }

    function enhanceDateInput(input) {
        if (input.dataset.useNativeDate === "true" || input.dataset.useNativeDate === "1") {
            return;
        }

        if (input._flatpickr) {
            syncAltInput(input._flatpickr);
            return;
        }

        var currentValue = input.value;
        var placeholder = input.getAttribute("placeholder");
        var existingClasses = toClassList(input.getAttribute("class"));
        var altClasses = existingClasses.slice();
        if (altClasses.indexOf("flatpickr-input") === -1) {
            altClasses.push("flatpickr-input");
        }

        var picker = flatpickr(input, {
            dateFormat: input.dataset.valueFormat || "Y-m-d",
            altInput: true,
            altFormat: input.dataset.displayFormat || "Y-m-d",
            altInputClass: altClasses.join(" "),
            allowInput: false,
            clickOpens: true,
            disableMobile: true,
            defaultDate: currentValue || undefined,
            onReady: function (_selectedDates, _dateStr, instance) {
                if (placeholder && instance.altInput) {
                    instance.altInput.setAttribute("placeholder", placeholder);
                }

                syncAltInput(instance);

                var form = input.form;
                if (form) {
                    if (!Array.isArray(form.__flatpickrInputs)) {
                        form.__flatpickrInputs = [];
                        form.addEventListener("reset", function () {
                            window.setTimeout(function () {
                                form.__flatpickrInputs.forEach(function (field) {
                                    if (field && field._flatpickr) {
                                        field._flatpickr.clear();
                                    }
                                });
                            }, 0);
                        });
                    }

                    if (form.__flatpickrInputs.indexOf(input) === -1) {
                        form.__flatpickrInputs.push(input);
                    }
                }
            },
            onValueUpdate: function (_selectedDates, _dateStr, instance) {
                syncAltInput(instance);
            }
        });

        if (picker && currentValue) {
            picker.setDate(currentValue, false, picker.config.dateFormat);
        }
    }

    function initFlatpickrForDateInputs(root) {
        if (typeof flatpickr !== "function") {
            return;
        }

        (root || document).querySelectorAll('input[type="date"]').forEach(function (input) {
            enhanceDateInput(input);
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            initFlatpickrForDateInputs(document);
        });
    } else {
        initFlatpickrForDateInputs(document);
    }

    var observer;
    if (typeof MutationObserver === "function") {
        observer = new MutationObserver(function (mutations) {
            mutations.forEach(function (mutation) {
                mutation.addedNodes.forEach(function (node) {
                    if (!(node instanceof HTMLElement)) {
                        return;
                    }

                    if (node.matches && node.matches('input[type="date"]')) {
                        enhanceDateInput(node);
                    }

                    if (node.querySelectorAll) {
                        node.querySelectorAll('input[type="date"]').forEach(function (childInput) {
                            enhanceDateInput(childInput);
                        });
                    }
                });
            });
        });

        observer.observe(document.documentElement, {
            childList: true,
            subtree: true
        });
    }
})();
