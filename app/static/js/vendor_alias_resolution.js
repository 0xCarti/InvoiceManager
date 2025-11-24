function initVendorAliasResolution(config) {
    const container = config && config.container ? config.container : null;
    if (!container) {
        return;
    }

    const unitsMap = (config && config.unitsMap) || {};
    const rows = container.querySelectorAll('[data-role="alias-row"]');

    function populateUnits(select, itemId) {
        if (!select) {
            return;
        }
        const units = unitsMap[itemId] || [];
        const selected = select.getAttribute('data-selected');
        const currentValue = select.value;
        select.innerHTML = '';
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = 'Select unit';
        select.appendChild(placeholder);
        units.forEach((unit) => {
            const opt = document.createElement('option');
            opt.value = unit.id;
            opt.textContent = unit.name;
            if (String(unit.id) === String(selected) || String(unit.id) === String(currentValue)) {
                opt.selected = true;
            }
            select.appendChild(opt);
        });
    }

    rows.forEach((row) => {
        const itemSelect = row.querySelector('[data-role="alias-item-select"]');
        const unitSelect = row.querySelector('[data-role="alias-unit-select"]');
        if (!itemSelect || !unitSelect) {
            return;
        }
        itemSelect.addEventListener('change', (event) => {
            populateUnits(unitSelect, event.target.value);
        });
        populateUnits(unitSelect, itemSelect.value);
    });
}
