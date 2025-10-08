(function (window) {
  'use strict';

  function formatNumber(value) {
    if (!Number.isFinite(value)) {
      return '';
    }
    const fixed = parseFloat(value.toFixed(4));
    return Number.isInteger(fixed) ? String(fixed) : String(fixed);
  }

  function parseInputValue(input) {
    if (!input) {
      return NaN;
    }
    if (window.NumericInput && typeof window.NumericInput.parseValue === 'function') {
      return window.NumericInput.parseValue(input);
    }
    if (typeof input === 'string') {
      return parseFloat(input);
    }
    return parseFloat(input.value);
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

    unitQtyInput.dataset.unitBaseQty = '';

    if (Number.isFinite(initialBaseQuantity)) {
      const selected = unitSelect.selectedOptions[0];
      const factor = parseFloat(selected.dataset.factor) || 1;
      if (factor > 0) {
        const rawUnitQty = Math.floor(initialBaseQuantity / factor);
        const unitQty = Number.isFinite(rawUnitQty) ? rawUnitQty : 0;
        let remainder = initialBaseQuantity - unitQty * factor;
        if (Math.abs(remainder) < 1e-9) {
          remainder = 0;
        }
        if (unitQty > 0) {
          const unitBaseQty = unitQty * factor;
          unitQtyInput.value = formatNumber(unitQty);
          unitQtyInput.dataset.unitBaseQty = String(unitBaseQty);
        }
        if (unitQty === 0) {
          if (initialBaseQuantity !== 0) {
            baseQtyInput.value = formatNumber(initialBaseQuantity);
          }
        } else if (remainder > 0) {
          baseQtyInput.value = formatNumber(remainder);
        }
      } else {
        baseQtyInput.value = formatNumber(initialBaseQuantity);
      }
    }

    updateLabels();

    unitSelect.addEventListener('change', function () {
      const storedBaseQty = parseInputValue(unitQtyInput.dataset.unitBaseQty);
      if (Number.isFinite(storedBaseQty)) {
        const selected = unitSelect.selectedOptions[0];
        const factor = parseFloat(selected.dataset.factor) || 1;
        const newUnitValue = storedBaseQty / factor;
        if (Number.isFinite(newUnitValue)) {
          unitQtyInput.value = formatNumber(newUnitValue);
          unitQtyInput.dataset.unitBaseQty = String(storedBaseQty);
        }
      }
      updateLabels();
    });

    unitQtyInput.addEventListener('input', function () {
      const unitValue = parseInputValue(unitQtyInput);
      if (Number.isFinite(unitValue)) {
        const selected = unitSelect.selectedOptions[0];
        const factor = parseFloat(selected.dataset.factor) || 1;
        const baseQty = unitValue * factor;
        if (Number.isFinite(baseQty)) {
          unitQtyInput.dataset.unitBaseQty = String(baseQty);
        } else {
          unitQtyInput.dataset.unitBaseQty = '';
        }
      } else {
        unitQtyInput.dataset.unitBaseQty = '';
      }
    });

    baseQtyInput.addEventListener('input', function () {
      // Base quantity represents additional base units and should not
      // overwrite the transfer unit quantity. No automatic updates needed.
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
