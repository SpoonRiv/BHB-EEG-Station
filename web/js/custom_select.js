/*
Copyright (c) 2026 BUAA BHB. All rights reserved.

文件功能: 为原生 select 提供可复用的圆角自定义下拉外观，并保持原始值与 change 事件同步
作者: Spoon
*/

function getDisplayText(selectEl) {
  const selectedOpt = selectEl.selectedOptions && selectEl.selectedOptions[0]
    ? selectEl.selectedOptions[0]
    : (selectEl.options && selectEl.options[0] ? selectEl.options[0] : null);
  return selectedOpt ? String(selectedOpt.textContent || '').trim() : '';
}

function buildOptionList(selectEl) {
  return Array.from(selectEl.options || []).filter((opt) => {
    if (opt.hidden) return false;
    if (opt.disabled && !String(opt.value || '').trim()) return false;
    return true;
  });
}

/**
 * 增强原生 select 为自定义圆角下拉。
 * 参数:
 * - selectEl: 需要增强的原生 select 元素。
 * 返回值:
 * - 返回控制对象，包含 sync 与 close 方法。
 * 边界条件:
 * - 若元素不存在、已增强或父节点不可用，则返回空实现对象。
 */
export function enhanceCustomSelect(selectEl) {
  if (!selectEl || selectEl.dataset.customSelectEnhanced === 'true' || !selectEl.parentElement) {
    return { sync() {}, close() {} };
  }

  const parent = selectEl.parentElement;
  const shell = document.createElement('div');
  shell.className = 'custom-select custom-select--generated';
  if (selectEl.style.width) shell.style.width = selectEl.style.width;

  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = 'custom-select__trigger';
  trigger.setAttribute('aria-haspopup', 'listbox');
  trigger.setAttribute('aria-expanded', 'false');

  const textEl = document.createElement('span');
  textEl.className = 'custom-select__text';

  const arrowEl = document.createElement('span');
  arrowEl.className = 'custom-select__arrow';
  arrowEl.setAttribute('aria-hidden', 'true');

  const menuEl = document.createElement('div');
  menuEl.className = 'custom-select__menu';
  menuEl.setAttribute('role', 'listbox');
  menuEl.hidden = true;

  trigger.appendChild(textEl);
  trigger.appendChild(arrowEl);
  shell.appendChild(trigger);
  shell.appendChild(menuEl);

  parent.insertBefore(shell, selectEl);
  shell.appendChild(selectEl);
  selectEl.classList.add('custom-select__native');
  selectEl.setAttribute('tabindex', '-1');
  selectEl.setAttribute('aria-hidden', 'true');
  selectEl.style.width = '';
  selectEl.dataset.customSelectEnhanced = 'true';

  const close = () => {
    shell.classList.remove('is-open');
    trigger.setAttribute('aria-expanded', 'false');
    menuEl.hidden = true;
  };

  const renderMenu = () => {
    const currentValue = String(selectEl.value || '').trim();
    const options = buildOptionList(selectEl);
    menuEl.innerHTML = '';

    for (const opt of options) {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'custom-select__option';
      item.setAttribute('role', 'option');
      const optionValue = String(opt.value || '').trim();
      const isSelected = optionValue === currentValue;
      item.setAttribute('aria-selected', String(isSelected));
      if (isSelected) item.classList.add('is-selected');

      const textSpan = document.createElement('span');
      textSpan.className = 'custom-select__option-text';
      textSpan.textContent = String(opt.textContent || '').trim();
      item.appendChild(textSpan);

      item.addEventListener('click', () => {
        selectEl.value = optionValue;
        selectEl.dispatchEvent(new Event('change', { bubbles: true }));
        close();
      });

      menuEl.appendChild(item);
    }
  };

  const sync = () => {
    textEl.textContent = getDisplayText(selectEl) || '请选择';
    trigger.disabled = !!selectEl.disabled;
    shell.classList.toggle('is-disabled', !!selectEl.disabled);
    renderMenu();
    if (selectEl.disabled || !menuEl.childElementCount) close();
  };

  trigger.addEventListener('click', () => {
    if (trigger.disabled || !menuEl.childElementCount) return;
    const willOpen = !shell.classList.contains('is-open');
    if (!willOpen) {
      close();
      return;
    }
    renderMenu();
    shell.classList.add('is-open');
    trigger.setAttribute('aria-expanded', 'true');
    menuEl.hidden = false;
  });

  document.addEventListener('pointerdown', (event) => {
    if (!shell.contains(event.target)) close();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') close();
  });

  selectEl.addEventListener('change', sync);

  const observer = new MutationObserver(() => sync());
  observer.observe(selectEl, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['disabled'],
  });

  sync();
  return { sync, close };
}
