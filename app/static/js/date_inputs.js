(function () {
    function initFlatpickrForDateInputs() {
        if (typeof flatpickr !== "function") {
            return;
        }

        document.querySelectorAll('input[type="date"]').forEach(function (input) {
            if (input.dataset.useNativeDate === "true" || input.dataset.useNativeDate === "1") {
                return;
            }

            var currentValue = input.value;
            flatpickr(input, {
                dateFormat: "Y-m-d",
                allowInput: true,
                disableMobile: true,
                defaultDate: currentValue || undefined
            });
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initFlatpickrForDateInputs);
    } else {
        initFlatpickrForDateInputs();
    }
})();
