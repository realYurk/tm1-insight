/* Shared real job progress, immediate feedback, resumable polling and checkpoint cancellation. */
(function () {
  'use strict';
  window.TM1JobProgress = class {
    constructor(kind, buttonId, statusId) {
      this.kind = kind;
      this.button = document.getElementById(buttonId);
      this.status = document.getElementById(statusId);
      this.panel = document.getElementById(kind + '-progress');
      this.stage = this.panel.querySelector('[data-job-stage]');
      this.bar = this.panel.querySelector('[data-job-bar]');
      this.count = this.panel.querySelector('[data-job-count]');
      this.cancel = this.panel.querySelector('[data-job-cancel]');
      this.result = this.panel.querySelector('[data-job-result]');
      this.epoch = 0;
      this.failures = 0;
      this.cancel.addEventListener('click', () => this.requestCancel());
      this.poll(++this.epoch);
      if (kind === 'audit') window.addEventListener('tm1-source-change', () => {
        this.panel.hidden = true;
        this.poll(++this.epoch);
      });
      window.addEventListener('pageshow', event => { if (event.persisted) this.poll(++this.epoch); });
      window.addEventListener('pagehide', () => { clearTimeout(this.timer); this.epoch++; });
    }
    render(state) {
      const p = state.progress;
      this.button.disabled = !!state.running;
      this.cancel.hidden = !state.running;
      this.cancel.disabled = !!state.cancel_requested;
      this.cancel.textContent = state.cancel_requested ? '正在取消…' : '取消任务';
      this.bar.hidden = !!state.error;
      this.result.hidden = !state.done || !!state.error;
      if (!state.running && !state.done) return;
      this.panel.hidden = false;
      if (p) {
        this.stage.textContent = '第 ' + p.stage + ' / ' + p.stages + ' 阶段 · ' + p.phase;
        if (p.total > 0 && p.done !== null) {
          this.bar.max = p.total; this.bar.value = p.done;
          this.count.textContent = p.done + ' / ' + p.total + ' · 本阶段 ' + p.percent + '%';
        } else {
          this.bar.removeAttribute('value');
          this.count.textContent = p.total === 0 ? '当前阶段没有对象' : '工作量尚不可计数，正在执行…';
        }
      }
      if (state.error) {
        this.count.textContent += state.cancelled ? ' · 已取消' : ' · 已停止';
        this.status.textContent = state.error;
        this.status.className = 'status-inline ' + (state.cancelled ? 'muted' : 'err');
      } else if (state.done) {
        this.bar.max = 1; this.bar.value = 1;
        this.status.textContent = this.kind === 'ingest' ? '采集、校验与切换完成，原模型保留。' : '扫描完成，结果已更新。';
        this.status.className = 'status-inline ok';
        this.count.textContent = '已完成';
        if (this.kind === 'ingest') window.dispatchEvent(new Event('tm1-source-change'));
      } else {
        this.status.className = 'status-inline muted';
        this.status.textContent = state.cancel_requested ? '已请求取消，等待当前操作结束。' : '后台执行中，可离开本页后返回查看进度。';
      }
    }
    async poll(epoch) {
      clearTimeout(this.timer);
      try {
        const response = await fetch('/api/' + this.kind + '/status', {cache: 'no-store'});
        const state = await response.json();
        if (epoch !== this.epoch) return;
        if (response.status === 409) {
          this.panel.hidden = true;
          this.button.disabled = false;
          this.status.textContent = state.error;
          this.status.className = 'status-inline err';
          return;
        }
        if (!response.ok) throw new Error(state.error || '无法读取任务状态。');
        this.failures = 0;
        this.render(state);
        if (state.running) this.timer = setTimeout(() => this.poll(epoch), 1000);
      } catch (error) {
        if (epoch !== this.epoch) return;
        this.status.textContent = '状态读取失败：' + error.message;
        this.status.className = 'status-inline err';
        if (++this.failures < 3) this.timer = setTimeout(() => this.poll(epoch), 1500);
        else {
          this.button.disabled = false; this.cancel.hidden = true; this.bar.hidden = true;
          this.count.textContent = '后台状态未知，刷新页面可重新核对。';
        }
      }
    }
    async start(body) {
      const epoch = ++this.epoch;
      clearTimeout(this.timer);
      this.failures = 0;
      this.button.disabled = true;
      this.panel.hidden = false;
      this.cancel.hidden = true;
      this.result.hidden = true;
      this.bar.removeAttribute('value');
      this.bar.hidden = false;
      this.stage.textContent = '正在启动任务…';
      this.count.textContent = '等待服务器确认阶段';
      this.status.className = 'status-inline muted';
      this.status.textContent = '正在启动，后台执行期间可离开本页。';
      try {
        const response = await fetch('/api/' + this.kind, {method: 'POST',
          headers: {'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined});
        const state = await response.json();
        if (epoch !== this.epoch) return;
        if (!response.ok && response.status !== 409) throw new Error(state.error || '启动失败。');
        await this.poll(epoch);
      } catch (error) {
        if (epoch !== this.epoch) return;
        this.status.textContent = error.message;
        this.status.className = 'status-inline err';
        this.stage.textContent = '启动或状态确认失败';
        this.bar.hidden = true;
        this.count.textContent = '请检查提示；刷新页面可重新核对后台状态。';
        this.button.disabled = false;
      }
    }
    async requestCancel() {
      this.cancel.disabled = true;
      try {
        const response = await fetch('/api/' + this.kind + '/cancel', {method: 'POST'});
        if (!response.ok) throw new Error('取消请求失败。');
        await this.poll(++this.epoch);
      } catch (error) { this.status.textContent = error.message; this.cancel.disabled = false; }
    }
  };
})();
