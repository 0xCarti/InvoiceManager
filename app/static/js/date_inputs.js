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

    function updateHiddenValue(instance) {
        if (!instance) {
            return;
        }

        var hiddenInput = instance._hiddenInput;
        if (!hiddenInput) {
            return;
        }

        if (instance.selectedDates && instance.selectedDates.length > 0) {
            var valueFormat = instance._valueFormat || hiddenInput.dataset.valueFormat || "Y-m-d";
            hiddenInput.value = instance.formatDate(instance.selectedDates[0], valueFormat);
        } else {
            hiddenInput.value = "";
        }
    }

    function registerFormReset(displayInput, hiddenInput, instance, valueFormat) {
        var form = hiddenInput.form || displayInput.form;
        if (!form) {
            return;
        }

        if (!Array.isArray(form.__flatpickrControls)) {
            form.__flatpickrControls = [];
            form.addEventListener("reset", function () {
                window.setTimeout(function () {
                    form.__flatpickrControls.forEach(function (control) {
                        var picker = control.picker;
                        var hidden = control.hidden;
                        var format = control.valueFormat;
                        if (!picker || !hidden) {
                            return;
                        }

                        var value = hidden.value;
                        if (value) {
                            picker.setDate(value, false, format);
                        } else {
                            picker.clear();
                        }
                    });
                }, 0);
            });
        }

        form.__flatpickrControls.push({
            picker: instance,
            hidden: hiddenInput,
            valueFormat: valueFormat
        });
    }

    function enhanceDateInput(input) {
        if (input.dataset.useNativeDate === "true" || input.dataset.useNativeDate === "1") {
            return;
        }

        if (input.dataset.flatpickrEnhanced === "1") {
            if (input._flatpickrProxy && input._flatpickrProxy._flatpickr) {
                input._flatpickrProxy._flatpickr.redraw();
            }
            return;
        }

        if (typeof flatpickr !== "function") {
            return;
        }

        var parent = input.parentNode;
        if (!parent) {
            return;
        }

        var existingValue = input.value;
        var placeholder = input.getAttribute("placeholder") || "";
        var classNames = toClassList(input.getAttribute("class"));
        var disabled = input.disabled;
        var required = input.required;
        var autocomplete = input.getAttribute("autocomplete");
        var valueFormat = input.dataset.valueFormat || "Y-m-d";
        var displayFormat = input.dataset.displayFormat || valueFormat;
        var minDateAttr = input.getAttribute("min");
        var maxDateAttr = input.getAttribute("max");

        var defaultDate = existingValue
            ? flatpickr.parseDate(existingValue, valueFormat) || existingValue
            : undefined;
        var minDate = minDateAttr
            ? flatpickr.parseDate(minDateAttr, valueFormat) || minDateAttr
            : undefined;
        var maxDate = maxDateAttr
            ? flatpickr.parseDate(maxDateAttr, valueFormat) || maxDateAttr
            : undefined;

        var displayInput = document.createElement("input");
        displayInput.type = "text";
        displayInput.name = "";
        displayInput.disabled = disabled;
        displayInput.required = required;
        displayInput.setAttribute("autocomplete", autocomplete || "off");
        if (placeholder) {
            displayInput.setAttribute("placeholder", placeholder);
        }

        if (classNames.length > 0) {
            displayInput.setAttribute("class", classNames.join(" "));
        }

        var originalId = input.id;
        if (originalId) {
            displayInput.id = originalId;
            input.id = originalId + "__value";
        }

        parent.insertBefore(displayInput, input);

        try {
            input.type = "hidden";
        } catch (err) {
            input.setAttribute("type", "hidden");
        }

        input.className = "";
        input.style.position = "absolute";
        input.style.left = "-9999px";
        input.style.width = "1px";
        input.style.height = "1px";
        input.style.padding = "0";
        input.style.margin = "0";
        input.dataset.flatpickrEnhanced = "1";

        var picker = flatpickr(displayInput, {
            dateFormat: displayFormat,
            allowInput: true,
            clickOpens: true,
            disableMobile: true,
            defaultDate: defaultDate,
            minDate: minDate,
            maxDate: maxDate,
            onReady: function (_selectedDates, _dateStr, instance) {
                if (placeholder) {
                    displayInput.setAttribute("placeholder", placeholder);
                }

                updateHiddenValue(instance);
                registerFormReset(displayInput, input, instance, valueFormat);
            },
            onChange: function (_selectedDates, _dateStr, instance) {
                updateHiddenValue(instance);
            },
            onValueUpdate: function (_selectedDates, _dateStr, instance) {
                updateHiddenValue(instance);
            }
        });

        picker._hiddenInput = input;
        picker._valueFormat = valueFormat;
        picker._displayInput = displayInput;

        if (existingValue) {
            picker.setDate(existingValue, false, valueFormat);
        }

        displayInput.addEventListener("blur", function () {
            if (displayInput.value.trim() === "") {
                picker.clear();
                input.value = "";
            }
        });

        displayInput.addEventListener("change", function () {
            var text = displayInput.value.trim();
            if (!text) {
                picker.clear();
                input.value = "";
                return;
            }

            var parsed = picker.parseDate(text, displayFormat);
            if (parsed) {
                picker.setDate(parsed, true);
            }
        });

        input._flatpickrProxy = displayInput;
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
