(function (window, document) {
  'use strict';

  const EXPRESSION_ALLOWED_RE = /^[0-9+\-*/().\s]+$/;
  const EXPRESSION_CHARS_RE = /[+\-*/()]/;
  const EXPRESSION_PREFIX = '=';
  const EXPRESSION_WARNING_MESSAGE = "To enter a calculation, start the value with '='.";

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
    if (text.startsWith(EXPRESSION_PREFIX)) {
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

  function requiresExpressionPrefix(value) {
    if (value === null || value === undefined) {
      return false;
    }
    const text = String(value).trim();
    if (!text || text.startsWith(EXPRESSION_PREFIX)) {
      return false;
    }
    let stripped = text;
    if (stripped.startsWith('+') || stripped.startsWith('-')) {
      stripped = stripped.slice(1).trimStart();
    }
    if (!stripped) {
      return false;
    }
    return EXPRESSION_CHARS_RE.test(stripped);
  }

  function getWarningElement(input) {
    if (!input) {
      return null;
    }
    const warningId = input.dataset.numericExpressionWarningId;
    if (warningId) {
      const existing = document.getElementById(warningId);
      if (existing && existing.parentNode) {
        return existing;
      }
    }
    const element = document.createElement('div');
    element.className = 'numeric-expression-warning text-danger small mt-1';
    element.setAttribute('role', 'alert');
    element.style.display = 'none';
    const id = 'numeric-expression-warning-' + Math.random().toString(36).slice(2);
    element.id = id;
    if (typeof input.insertAdjacentElement === 'function') {
      input.insertAdjacentElement('afterend', element);
    } else if (input.parentNode) {
      input.parentNode.insertBefore(element, input.nextSibling);
    }
    input.dataset.numericExpressionWarningId = id;
    return element;
  }

  function showWarningMessage(input, message) {
    const element = getWarningElement(input);
    if (!element) {
      return;
    }
    element.textContent = message;
    element.style.display = '';
  }

  function hideWarningMessage(input) {
    const warningId = input && input.dataset.numericExpressionWarningId;
    if (!warningId) {
      return;
    }
    const element = document.getElementById(warningId);
    if (!element) {
      return;
    }
    element.textContent = '';
    element.style.display = 'none';
  }

  function updateExpressionWarning(input, shouldReport) {
    if (!input) {
      return;
    }
    const needsPrefix = requiresExpressionPrefix(input.value);
    if (needsPrefix) {
      input.setCustomValidity(EXPRESSION_WARNING_MESSAGE);
      showWarningMessage(input, EXPRESSION_WARNING_MESSAGE);
      if (shouldReport && input.dataset.numericExpressionWarned !== '1') {
        if (typeof input.reportValidity === 'function') {
          input.reportValidity();
        }
        input.dataset.numericExpressionWarned = '1';
      }
    } else {
      input.setCustomValidity('');
      hideWarningMessage(input);
      delete input.dataset.numericExpressionWarned;
    }
  }

  function handleExpressionInput(event) {
    updateExpressionWarning(event.currentTarget || event.target, true);
  }

  function handleExpressionBlur(event) {
    updateExpressionWarning(event.currentTarget || event.target, false);
  }

  function handleExpressionInvalid(event) {
    updateExpressionWarning(event.currentTarget || event.target, true);
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
    getWarningElement(input);
    if (input.dataset.numericExpressionWarningBound !== '1') {
      input.addEventListener('input', handleExpressionInput);
      input.addEventListener('change', handleExpressionBlur);
      input.addEventListener('blur', handleExpressionBlur);
      input.addEventListener('invalid', handleExpressionInvalid);
      input.dataset.numericExpressionWarningBound = '1';
    }
    input.dataset.numericExpressionEnabled = '1';
    updateExpressionWarning(input, false);
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
  };
})(window, document);
