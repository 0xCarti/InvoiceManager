(function () {
    function initFlatpickrForDateInputs() {
        if (typeof flatpickr !== "function") {
            return;
        }

        document.querySelectorAll('input[type="date"]').forEach(function (input) {
            if (input.dataset.useNativeDate === "true" || input.dataset.useNativeDate === "1") {
                return;
            }

            if (input._flatpickr) {
                return;
            }

            var currentValue = input.value;
            var placeholder = input.getAttribute("placeholder");
            var existingClasses = input.getAttribute("class") || "";

            var picker = flatpickr(input, {
                dateFormat: input.dataset.valueFormat || "Y-m-d",
                altInput: true,
                altFormat: input.dataset.displayFormat || "Y-m-d",
                altInputClass: (existingClasses + " flatpickr-input").trim(),
                allowInput: false,
                disableMobile: true,
                defaultDate: currentValue || undefined,
                onReady: function (_selectedDates, _dateStr, instance) {
                    if (placeholder && instance.altInput) {
                        instance.altInput.setAttribute("placeholder", placeholder);
                    }
                }
            });

            if (picker && currentValue) {
                // Ensure the alt input reflects any existing ISO value from the server.
                picker.setDate(currentValue, false, picker.config.dateFormat);
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initFlatpickrForDateInputs);
    } else {
        initFlatpickrForDateInputs();
    }
})();
