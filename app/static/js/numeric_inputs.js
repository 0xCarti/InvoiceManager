(function (window, document) {
  'use strict';

  const EXPRESSION_ALLOWED_RE = /^[0-9+\-*/().\s]+$/;

  function evaluateExpression(expression) {
    if (typeof expression !== 'string') {
      return NaN;
    }
    const trimmed = expression.trim();
    if (!trimmed || !EXPRESSION_ALLOWED_RE.test(trimmed)) {
      return NaN;
    }
    try {
      const result = Function('"use strict"; return (' + trimmed + ');')();
      return typeof result === 'number' && Number.isFinite(result)
        ? result
        : NaN;
    } catch (error) {
      return NaN;
    }
  }

  function parseValue(value) {
    if (value instanceof window.HTMLInputElement) {
      value = value.value;
    }
    if (value === null || value === undefined) {
      return NaN;
    }
    const text = String(value).trim();
    if (!text) {
      return NaN;
    }
    if (text.startsWith('=')) {
      return evaluateExpression(text.slice(1));
    }
    const normalized = text.replace(/,/g, '');
    const numeric = Number(normalized);
    if (Number.isFinite(numeric)) {
      return numeric;
    }
    if (EXPRESSION_ALLOWED_RE.test(normalized)) {
      return NaN;
    }
    return NaN;
  }

  function parseOrDefault(value, defaultValue) {
    const parsed = parseValue(value);
    return Number.isFinite(parsed) ? parsed : defaultValue;
  }

  function getStepDecimalPlaces(input) {
    if (!input) {
      return null;
    }
    const stepAttr = input.getAttribute('step');
    if (!stepAttr) {
      return null;
    }
    const trimmed = stepAttr.trim();
    if (!trimmed || trimmed.toLowerCase() === 'any') {
      return null;
    }
    const decimalIndex = trimmed.indexOf('.');
    if (decimalIndex === -1) {
      return null;
    }
    const decimalPortion = trimmed.slice(decimalIndex + 1).replace(/[^0-9].*$/, '');
    return decimalPortion ? decimalPortion.length : null;
  }

  function formatResolvedValue(input, value) {
    if (!Number.isFinite(value)) {
      return '';
    }
    let rounded = value;
    const decimalPlaces = getStepDecimalPlaces(input);
    const places = Number.isInteger(decimalPlaces) ? decimalPlaces : 10;
    try {
      rounded = Number(value.toFixed(places));
    } catch (error) {
      rounded = value;
    }
    if (!Number.isFinite(rounded)) {
      rounded = value;
    }
    return rounded.toString();
  }

  function resolveExpressionForInput(input, { dispatchEvents = true } = {}) {
    if (!(input instanceof window.HTMLInputElement)) {
      return;
    }
    const rawValue = input.value;
    if (typeof rawValue !== 'string') {
      return;
    }
    const trimmed = rawValue.trim();
    if (!trimmed || trimmed.charAt(0) !== '=') {
      return;
    }
    const expression = trimmed.slice(1);
    const result = evaluateExpression(expression);
    if (!Number.isFinite(result)) {
      return;
    }
    const formatted = formatResolvedValue(input, result);
    if (formatted === rawValue) {
      return;
    }
    input.value = formatted;
    if (dispatchEvents) {
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }

  function handleInputBlur(event) {
    resolveExpressionForInput(event.target);
  }

  function enableInput(input) {
    if (!input || input.dataset.numericExpressionEnabled === '1') {
      return;
    }
    const currentType = input.getAttribute('type');
    if (currentType && currentType.toLowerCase() === 'number') {
      input.setAttribute('data-original-type', currentType);
      try {
        input.type = 'text';
      } catch (error) {
        input.setAttribute('type', 'text');
      }
    }
    if (!input.hasAttribute('inputmode')) {
      input.setAttribute('inputmode', 'decimal');
    }
    input.addEventListener('blur', handleInputBlur);
    input.dataset.numericExpressionEnabled = '1';
  }

  function enableWithin(root) {
    if (!root) {
      return;
    }
    if (root instanceof window.HTMLInputElement) {
      enableInput(root);
      return;
    }
    const inputs = root.querySelectorAll('input[type="number"], input[data-numeric-input]');
    inputs.forEach(enableInput);
  }

  document.addEventListener('DOMContentLoaded', function () {
    enableWithin(document);
  });

  const observer = new MutationObserver(function (mutations) {
    mutations.forEach(function (mutation) {
      mutation.addedNodes.forEach(function (node) {
        if (!(node instanceof window.Element)) {
          return;
        }
        if (node.matches('input[type="number"], input[data-numeric-input]')) {
          enableInput(node);
        } else {
          enableWithin(node);
        }
      });
    });
  });

  observer.observe(document.documentElement, {
    childList: true,
    subtree: true,
  });

  window.NumericInput = {
    enableWithin: enableWithin,
    parseValue: parseValue,
    parseOrDefault: parseOrDefault,
    evaluateExpression: evaluateExpression,
    resolveExpressionForInput: resolveExpressionForInput,
  };
})(window, document);
