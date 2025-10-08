(function (window) {
  'use strict';

  function formatNumber(value) {
    if (!Number.isFinite(value)) {
      return '';
    }
    const fixed = parseFloat(value.toFixed(4));
    return Number.isInteger(fixed) ? String(fixed) : String(fixed);
  }

  function formatRatio(unitName, factor, baseUnit) {
    const formattedFactor = formatNumber(factor);
    return `${unitName} - ${formattedFactor} ${baseUnit}`;
  }

  function ensureUnits(data) {
    const baseUnit = data.base_unit;
    const units = Array.isArray(data.units) ? data.units.slice() : [];
    const hasDefault = units.some(function (unit) {
      return unit.transfer_default;
    });
    units.unshift({
      id: 0,
      name: baseUnit,
      factor: 1,
      transfer_default: !hasDefault,
    });
    return units;
  }

  function createTransferRow(options) {
    const {
      prefix,
      index,
      itemId,
      itemName,
      unitsData,
      existingBaseQuantity,
    } = options;

    const units = ensureUnits(unitsData);
    const baseUnit = unitsData.base_unit;
    const defaultUnit = units.find(function (unit) {
      return unit.transfer_default;
    }) || units[0];

    const listItem = document.createElement('div');
    listItem.className = 'transfer-item card mb-3';
    listItem.dataset.itemId = itemId;

    const cardBody = document.createElement('div');
    cardBody.className = 'card-body';
    listItem.appendChild(cardBody);

    const header = document.createElement('div');
    header.className = 'd-flex justify-content-between align-items-start flex-wrap gap-2';
    cardBody.appendChild(header);

    const nameEl = document.createElement('div');
    nameEl.className = 'fw-bold flex-grow-1';
    nameEl.textContent = itemName;
    header.appendChild(nameEl);

    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'btn btn-outline-danger btn-sm transfer-delete-item';
    deleteBtn.textContent = 'Remove';
    deleteBtn.addEventListener('click', function () {
      listItem.remove();
    });
    header.appendChild(deleteBtn);

    const hiddenInput = document.createElement('input');
    hiddenInput.type = 'hidden';
    hiddenInput.name = `${prefix}-${index}-item`;
    hiddenInput.value = itemId;
    cardBody.appendChild(hiddenInput);

    const row = document.createElement('div');
    row.className = 'row g-3 align-items-end mt-1';
    cardBody.appendChild(row);

    const unitCol = document.createElement('div');
    unitCol.className = 'col-md-4 col-sm-6';
    row.appendChild(unitCol);

    const unitLabel = document.createElement('label');
    unitLabel.className = 'form-label mb-1';
    unitLabel.htmlFor = `${prefix}-${index}-unit`;
    unitLabel.textContent = 'Unit of Measure';
    unitCol.appendChild(unitLabel);

    const unitSelect = document.createElement('select');
    unitSelect.className = 'form-select transfer-unit-select';
    unitSelect.name = `${prefix}-${index}-unit`;
    unitSelect.id = `${prefix}-${index}-unit`;
    unitCol.appendChild(unitSelect);

    units.forEach(function (unit) {
      const option = document.createElement('option');
      const unitName = unit.id === 0 ? baseUnit : unit.name;
      const factor = Number.isFinite(unit.factor) ? unit.factor : 1;
      option.value = unit.id || 0;
      option.dataset.factor = factor;
      option.dataset.unitName = unitName;
      option.selected = unit.id === defaultUnit.id;
      option.textContent = formatRatio(unitName, factor, baseUnit);
      unitSelect.appendChild(option);
    });

    const unitQtyCol = document.createElement('div');
    unitQtyCol.className = 'col-md-4 col-sm-6';
    row.appendChild(unitQtyCol);

    const unitQtyLabel = document.createElement('label');
    unitQtyLabel.className = 'form-label mb-1 unit-quantity-label';
    unitQtyLabel.htmlFor = `${prefix}-${index}-quantity`;
    unitQtyCol.appendChild(unitQtyLabel);

    const unitQtyInput = document.createElement('input');
    unitQtyInput.type = 'text';
    unitQtyInput.setAttribute('inputmode', 'decimal');
    unitQtyInput.className = 'form-control unit-quantity';
    unitQtyInput.name = `${prefix}-${index}-quantity`;
    unitQtyInput.id = `${prefix}-${index}-quantity`;
    unitQtyInput.placeholder = 'Transfer Qty';
    unitQtyInput.dataset.baseQty = '';
    unitQtyCol.appendChild(unitQtyInput);

    const baseQtyCol = document.createElement('div');
    baseQtyCol.className = 'col-md-4 col-sm-6';
    row.appendChild(baseQtyCol);

    const baseQtyLabel = document.createElement('label');
    baseQtyLabel.className = 'form-label mb-1';
    baseQtyLabel.htmlFor = `${prefix}-${index}-base_quantity`;
    baseQtyLabel.textContent = `${baseUnit} Quantity`;
    baseQtyCol.appendChild(baseQtyLabel);

    const baseInputGroup = document.createElement('div');
    baseInputGroup.className = 'input-group';
    baseQtyCol.appendChild(baseInputGroup);

    const baseQtyInput = document.createElement('input');
    baseQtyInput.type = 'text';
    baseQtyInput.setAttribute('inputmode', 'decimal');
    baseQtyInput.className = 'form-control base-quantity';
    baseQtyInput.name = `${prefix}-${index}-base_quantity`;
    baseQtyInput.id = `${prefix}-${index}-base_quantity`;
    baseQtyInput.placeholder = 'Base Qty';
    baseInputGroup.appendChild(baseQtyInput);

    const baseUnitTag = document.createElement('span');
    baseUnitTag.className = 'input-group-text';
    baseUnitTag.textContent = baseUnit;
    baseInputGroup.appendChild(baseUnitTag);

    function updateLabels() {
      const selected = unitSelect.selectedOptions[0];
      const unitName = selected.dataset.unitName || selected.textContent || baseUnit;
      unitQtyLabel.textContent = `${unitName} Quantity`;
    }

    function updateUnitFromBase(baseValue) {
      const selected = unitSelect.selectedOptions[0];
      const factor = parseFloat(selected.dataset.factor) || 1;
      if (Number.isFinite(baseValue)) {
        unitQtyInput.value = formatNumber(baseValue / factor);
        unitQtyInput.dataset.baseQty = String(baseValue);
      } else {
        unitQtyInput.value = '';
        unitQtyInput.dataset.baseQty = '';
      }
    }

    function updateBaseFromUnit(unitValue) {
      const selected = unitSelect.selectedOptions[0];
      const factor = parseFloat(selected.dataset.factor) || 1;
      if (Number.isFinite(unitValue)) {
        const baseValue = unitValue * factor;
        baseQtyInput.value = formatNumber(baseValue);
        unitQtyInput.dataset.baseQty = String(baseValue);
      } else {
        baseQtyInput.value = '';
        unitQtyInput.dataset.baseQty = '';
      }
    }

    const parsedExisting =
      typeof existingBaseQuantity === 'number' &&
      Number.isFinite(existingBaseQuantity)
        ? existingBaseQuantity
        : window.NumericInput
        ? window.NumericInput.parseValue(existingBaseQuantity)
        : parseFloat(existingBaseQuantity);
    const initialBaseQuantity = Number.isFinite(parsedExisting)
      ? parsedExisting
      : NaN;

    if (Number.isFinite(initialBaseQuantity)) {
      baseQtyInput.value = formatNumber(initialBaseQuantity);
      updateUnitFromBase(initialBaseQuantity);
    } else {
      unitQtyInput.value = '';
      baseQtyInput.value = '';
      unitQtyInput.dataset.baseQty = '';
    }

    updateLabels();

    unitSelect.addEventListener('change', function () {
      const baseQty = window.NumericInput
        ? window.NumericInput.parseValue(unitQtyInput.dataset.baseQty)
        : parseFloat(unitQtyInput.dataset.baseQty);
      if (Number.isFinite(baseQty)) {
        updateUnitFromBase(baseQty);
      } else {
        unitQtyInput.value = '';
      }
      updateLabels();
    });

    unitQtyInput.addEventListener('input', function () {
      const unitValue = window.NumericInput
        ? window.NumericInput.parseValue(unitQtyInput)
        : parseFloat(unitQtyInput.value);
      if (Number.isFinite(unitValue)) {
        updateBaseFromUnit(unitValue);
      } else {
        unitQtyInput.dataset.baseQty = '';
        baseQtyInput.value = '';
      }
    });

    baseQtyInput.addEventListener('input', function () {
      const baseValue = window.NumericInput
        ? window.NumericInput.parseValue(baseQtyInput)
        : parseFloat(baseQtyInput.value);
      if (Number.isFinite(baseValue)) {
        updateUnitFromBase(baseValue);
      } else {
        unitQtyInput.value = '';
        unitQtyInput.dataset.baseQty = '';
      }
    });

    if (window.NumericInput) {
      window.NumericInput.enableWithin(listItem);
    }

    return listItem;
  }

  window.TransferWorkflow = {
    createRow: createTransferRow,
    formatNumber: formatNumber,
    formatRatio: formatRatio,
  };
})(window);
