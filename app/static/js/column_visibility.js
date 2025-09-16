(function () {
    document.addEventListener('DOMContentLoaded', function () {
        var table = document.getElementById('itemsTable');
        if (!table) {
            return;
        }

        var checkboxes = Array.prototype.slice.call(document.querySelectorAll('.column-toggle'));
        if (!checkboxes.length) {
            return;
        }

        var storageKey = 'itemsTableColumnVisibility';
        var storedState = {};
        try {
            var saved = window.localStorage.getItem(storageKey);
            if (saved) {
                storedState = JSON.parse(saved) || {};
            }
        } catch (err) {
            storedState = {};
        }

        checkboxes.forEach(function (checkbox) {
            var columnClass = checkbox.dataset.columnTarget;
            if (!columnClass) {
                return;
            }
            if (Object.prototype.hasOwnProperty.call(storedState, columnClass)) {
                checkbox.checked = Boolean(storedState[columnClass]);
            }
        });

        if (!checkboxes.some(function (checkbox) { return checkbox.checked; })) {
            checkboxes[0].checked = true;
        }

        applyVisibility();
        persistState();

        checkboxes.forEach(function (checkbox) {
            checkbox.addEventListener('change', function () {
                if (!checkbox.checked) {
                    var visibleCount = checkboxes.filter(function (cb) { return cb.checked; }).length;
                    if (visibleCount === 0) {
                        checkbox.checked = true;
                        window.alert('At least one data column must remain visible.');
                        return;
                    }
                }
                applyVisibility();
                persistState();
            });
        });

        var observerTarget = table.tBodies && table.tBodies.length ? table.tBodies[0] : table;
        var observer = new MutationObserver(function (mutations) {
            for (var i = 0; i < mutations.length; i += 1) {
                var mutation = mutations[i];
                if (mutation.type === 'childList' && mutation.addedNodes.length) {
                    applyVisibility();
                    break;
                }
            }
        });
        observer.observe(observerTarget, { childList: true, subtree: true });

        function applyVisibility() {
            checkboxes.forEach(function (checkbox) {
                var columnClass = checkbox.dataset.columnTarget;
                if (!columnClass) {
                    return;
                }
                var cells = table.querySelectorAll('.' + columnClass);
                cells.forEach(function (cell) {
                    if (checkbox.checked) {
                        cell.classList.remove('d-none');
                    } else {
                        cell.classList.add('d-none');
                    }
                });
            });
        }

        function persistState() {
            var state = {};
            checkboxes.forEach(function (checkbox) {
                var columnClass = checkbox.dataset.columnTarget;
                if (!columnClass) {
                    return;
                }
                state[columnClass] = checkbox.checked;
            });
            try {
                window.localStorage.setItem(storageKey, JSON.stringify(state));
            } catch (err) {
                /* Ignore storage errors */
            }
        }
    });
})();
