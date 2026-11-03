(function () {
  'use strict';
  const form = document.getElementById('package-check-form');
  if (!form) return;
  const input = document.getElementById('package-check-file');
  const status = document.getElementById('package-check-status');
  const button = form.querySelector('button');
  input.addEventListener('change', () => { status.textContent = ''; });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!input.files.length) return;
    const data = new FormData();
    data.append('file', input.files[0]);
    button.disabled = true;
    status.textContent = '正在检查本地文件…';
    try {
      const response = await fetch('/api/architecture/verify-package', {method:'POST', body:data});
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || '检查失败，请重试。');
      status.textContent = `检查通过：${result.files_checked} 个文件与清单一致，记录 ${result.omissions} 项遗漏。校验不证明来源可信或资料完整。`;
    } catch (error) {
      status.textContent = error.message || '检查失败，请重试。';
    } finally {
      button.disabled = false;
    }
  });
})();
