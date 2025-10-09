(function () {
    function buildAltInputClass(input) {
        var classes = ["flatpickr-alt-input"];
        if (input && input.classList && input.classList.length) {
            input.classList.forEach(function (cls) {
                if (cls && classes.indexOf(cls) === -1) {
                    classes.push(cls);
                }
            });
        } else if (input && input.className) {
            classes.push(input.className);
        }
        return classes.join(" ");
    }

    function enhanceDateInput(input) {
        if (!input || input.dataset.useNativeDate === "true" || input.dataset.useNativeDate === "1") {
            return;
        }

        if (input.dataset.flatpickrEnhanced === "1") {
            return;
        }

        if (typeof flatpickr !== "function") {
            return;
        }

        var valueFormat = input.dataset.valueFormat || "Y-m-d";
        var displayFormat = input.dataset.displayFormat || "Y-m-d";
        var placeholder = input.getAttribute("placeholder") || "";
        var initialValue = input.value;
        var minAttr = input.getAttribute("min");
        var maxAttr = input.getAttribute("max");
        var lastIsoValue = initialValue || "";
        var lastDisplayValue = "";

        var picker = flatpickr(input, {
            allowInput: true,
            altInput: true,
            altInputClass: buildAltInputClass(input),
            altFormat: displayFormat,
            clickOpens: true,
            dateFormat: valueFormat,
            defaultDate: initialValue || null,
            disableMobile: true,
            minDate: minAttr || null,
            maxDate: maxAttr || null,
            onReady: function (selectedDates, _dateStr, instance) {
                input.dataset.flatpickrEnhanced = "1";

                if (instance.altInput) {
                    instance.altInput.setAttribute("data-flatpickr-alt", "1");
                    if (placeholder) {
                        instance.altInput.setAttribute("placeholder", placeholder);
                    }

                    var originalId = input.getAttribute("id");
                    if (originalId) {
                        input.setAttribute("data-original-id", originalId);
                        instance.altInput.id = originalId;
                        input.id = originalId + "__value";
                        document.querySelectorAll('label[for="' + originalId + '"]').forEach(function (label) {
                            label.setAttribute("for", instance.altInput.id);
                        });
                    }
                }

                if (selectedDates && selectedDates.length > 0) {
                    updateLastValues(instance, selectedDates[0]);
                } else if (initialValue) {
                    var parsedInitial = instance.parseDate(initialValue, valueFormat);
                    if (parsedInitial) {
                        updateLastValues(instance, parsedInitial);
                    }
                } else {
                    clearValues(instance);
                }
            },
            onChange: function (selectedDates, _dateStr, instance) {
                if (selectedDates && selectedDates.length > 0) {
                    updateLastValues(instance, selectedDates[0]);
                } else {
                    clearValues(instance);
                }
            },
            onValueUpdate: function (selectedDates, dateStr, instance) {
                if (selectedDates && selectedDates.length > 0) {
                    updateLastValues(instance, selectedDates[0]);
                } else if (!dateStr) {
                    clearValues(instance);
                }
            },
            onClose: function (selectedDates, dateStr, instance) {
                if (!dateStr) {
                    clearValues(instance);
                    return;
                }

                if (selectedDates && selectedDates.length > 0) {
                    updateLastValues(instance, selectedDates[0]);
                    return;
                }

                var parsed = instance.parseDate(dateStr, displayFormat) || instance.parseDate(dateStr, valueFormat);
                if (parsed) {
                    instance.setDate(parsed, false, valueFormat);
                    updateLastValues(instance, parsed);
                } else {
                    restoreLastDisplay(instance);
                }
            }
        });

        function updateLastValues(instance, dateObj) {
            if (!instance) {
                return;
            }
            var iso = instance.formatDate(dateObj, valueFormat);
            var display = instance.formatDate(dateObj, displayFormat);
            instance.input.value = iso;
            if (instance.altInput) {
                instance.altInput.value = display;
            }
            lastIsoValue = iso;
            lastDisplayValue = display;
        }

        function clearValues(instance) {
            if (!instance) {
                return;
            }
            instance.input.value = "";
            if (instance.altInput) {
                instance.altInput.value = "";
            }
            lastIsoValue = "";
            lastDisplayValue = "";
        }

        function restoreLastDisplay(instance) {
            if (!instance) {
                return;
            }
            instance.input.value = lastIsoValue;
            if (instance.altInput) {
                instance.altInput.value = lastDisplayValue;
            }
        }

        if (input.form) {
            var form = input.form;
            form.addEventListener("reset", function () {
                window.setTimeout(function () {
                    if (initialValue) {
                        picker.setDate(initialValue, false, valueFormat);
                        var parsedInitial = picker.parseDate(initialValue, valueFormat);
                        if (parsedInitial) {
                            updateLastValues(picker, parsedInitial);
                        }
                    } else {
                        picker.clear();
                        clearValues(picker);
                    }
                }, 0);
            });
        }
    }

    function initFlatpickrForDateInputs(root) {
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

    if (typeof MutationObserver === "function") {
        var observer = new MutationObserver(function (mutations) {
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
