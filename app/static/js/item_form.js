(function (window, document) {
    'use strict';

    function getTemplateHtml(templateEl) {
        if (!templateEl) {
            return '';
        }
        if (templateEl.tagName === 'TEMPLATE') {
            return templateEl.innerHTML.trim();
        }
        return (templateEl.innerHTML || templateEl.textContent || '').trim();
    }

    function createUnitRow(templateHtml, index) {
        if (!templateHtml) {
            return null;
        }
        var wrapper = document.createElement('div');
        wrapper.innerHTML = templateHtml.replace(/__index__/g, String(index));
        return wrapper.firstElementChild;
    }

    function initDefaultsHandling(unitsContainer) {
        unitsContainer.addEventListener('change', function (event) {
            var target = event.target;
            if (target.classList.contains('default-receiving') && target.checked) {
                unitsContainer.querySelectorAll('.default-receiving').forEach(function (checkbox) {
                    if (checkbox !== target) {
                        checkbox.checked = false;
                    }
                });
            } else if (target.classList.contains('default-transfer') && target.checked) {
                unitsContainer.querySelectorAll('.default-transfer').forEach(function (checkbox) {
                    if (checkbox !== target) {
                        checkbox.checked = false;
                    }
                });
            }
        });
    }

    function initRemovalHandling(unitsContainer) {
        unitsContainer.addEventListener('click', function (event) {
            var button = event.target.closest('.remove-unit');
            if (!button) {
                return;
            }
            var row = button.closest('.unit-row');
            if (row) {
                row.remove();
            }
        });
    }

    function initItemForm(form) {
        if (!form || form.dataset.itemFormInitialized === 'true') {
            return;
        }

        var unitsContainer = form.querySelector('#units-container');
        var templateEl = form.querySelector('#unit-row-template');
        if (!unitsContainer || !templateEl) {
            form.dataset.itemFormInitialized = 'true';
            return;
        }

        var addButton = form.querySelector('#add-unit');
        if (!addButton) {
            form.dataset.itemFormInitialized = 'true';
            return;
        }

        var templateHtml = getTemplateHtml(templateEl);
        var nextIndexAttr = form.getAttribute('data-next-index');
        var nextIndex = parseInt(nextIndexAttr || '', 10);
        if (isNaN(nextIndex)) {
            nextIndex = unitsContainer.querySelectorAll('.unit-row').length;
        }

        addButton.addEventListener('click', function () {
            var newRow = createUnitRow(templateHtml, nextIndex);
            if (newRow) {
                unitsContainer.appendChild(newRow);
                nextIndex += 1;
                form.setAttribute('data-next-index', String(nextIndex));
            }
        });

        initRemovalHandling(unitsContainer);
        initDefaultsHandling(unitsContainer);

        form.dataset.itemFormInitialized = 'true';
    }

    function init(container) {
        if (!container) {
            return;
        }

        if (container.matches && container.matches('form[data-item-form]')) {
            initItemForm(container);
            return;
        }

        var form = container.querySelector && container.querySelector('form[data-item-form]');
        if (form) {
            initItemForm(form);
        }
    }

    window.ItemForm = window.ItemForm || {};
    window.ItemForm.init = function (container) {
        if (!container) {
            return;
        }
        if (container instanceof window.Element || container === window.document) {
            init(container);
        } else if (typeof container.length === 'number') {
            Array.prototype.forEach.call(container, init);
        }
    };

    document.addEventListener('DOMContentLoaded', function () {
        var forms = document.querySelectorAll('form[data-item-form]');
        if (forms.length) {
            window.ItemForm.init(forms);
        }
    });
}(window, document));
