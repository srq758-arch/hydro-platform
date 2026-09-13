/*
 * 纯 Node 的前端状态回归验证。
 * 不依赖浏览器或 pywebview：加载 app.js 的状态管理前缀，并以极小 DOM 替身
 * 验证“离开页面再返回”会恢复输入、筛选、勾选和动态结果区域。
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const appPath = process.argv[2];
if (!appPath) throw new Error('Missing app.js path');
const source = fs.readFileSync(appPath, 'utf8');
const cutoff = source.indexOf('// ---------- 通用模态框组件 ----------');
if (cutoff < 0) throw new Error('Cannot locate page-state module boundary');

const ids = new Map();
const main = {
  children: [{}], scrollTop: 0, controls: [], regions: [],
  querySelectorAll(selector) {
    if (selector.includes('contenteditable')) return this.controls;
    if (selector === '[data-persist-region]') return this.regions;
    return [];
  },
};
ids.set('main-content', main);
const sandbox = {
  console,
  window: {},
  document: { getElementById: id => ids.get(id) || null },
};
const expose = `\nglobalThis.__pageState = {
  setAppState: value => { appState = value; },
  getAppState: () => appState,
  routeStateKey, routeParams, shouldRestorePageState, snapshotCurrentPageState, restorePageState
};`;
vm.runInNewContext(source.slice(0, cutoff) + expose, sandbox, { filename: appPath });
const pageState = sandbox.__pageState;

function input(id, value, type = 'text') {
  return { tagName: 'INPUT', id, name: '', type, value, checked: false, dataset: {} };
}
function select(id, value) {
  return { tagName: 'SELECT', id, name: '', type: 'select-one', value, checked: false, dataset: {}, multiple: false };
}
function checkbox(id, checked) {
  return { tagName: 'INPUT', id, name: '', type: 'checkbox', value: 'on', checked, dataset: {} };
}
function region(key, html, style = 'display:block') {
  return {
    tagName: 'DIV', id: key, dataset: { persistRegion: key }, innerHTML: html,
    className: 'card', styleValue: style,
    getAttribute(name) { return name === 'style' ? this.styleValue : null; },
    setAttribute(name, value) { if (name === 'style') this.styleValue = value; },
    removeAttribute(name) { if (name === 'style') this.styleValue = null; },
  };
}

// 智能任务草稿：包含用户输入和已经得到的候选结果。
pageState.setAppState({ route: 'intelligent-tasks', params: {}, pageStates: Object.create(null) });
const prompt = { tagName: 'TEXTAREA', id: 'intelligent-task-prompt', name: '', type: 'textarea', value: '收集乌东德 2023 年发电量，只要官方年报', checked: false, dataset: {} };
const intelligentResult = region('intelligent-task-result', '<table><tbody><tr><td>候选 PDF</td></tr></tbody></table>');
main.controls = [prompt];
main.regions = [intelligentResult];
main.scrollTop = 128;
pageState.snapshotCurrentPageState();

// 模拟该页面被导航后的全量重绘。
const freshPrompt = { ...prompt, value: '' };
const freshResult = region('intelligent-task-result', '');
main.controls = [freshPrompt];
main.regions = [freshResult];
main.scrollTop = 0;
pageState.restorePageState('intelligent-tasks');
assert.equal(freshPrompt.value, prompt.value);
assert.equal(freshResult.innerHTML, intelligentResult.innerHTML);
assert.equal(main.scrollTop, 128);

// 通用表单：新增数据的 URL、年份、筛选项、复核勾选都由同一机制覆盖。
pageState.setAppState({ route: 'add-data', params: {}, pageStates: Object.create(null) });
const url = input('input-url', 'https://example.test/annual-report.pdf');
const year = input('input-target-year', '2023', 'number');
const country = select('country-filter', 'China');
const selected = checkbox('check-42', true);
const localFile = input('input-csv-file', 'do-not-copy.csv', 'file');
const secret = input('llm-api-key', 'do-not-copy', 'password');
const taskResult = region('task-result', '<p>抽取到 3 条候选</p>', 'margin-top:20px;display:block');
main.controls = [url, year, country, selected, localFile, secret];
main.regions = [taskResult];
pageState.snapshotCurrentPageState();

const rerendered = [input('input-url', ''), input('input-target-year', '', 'number'), select('country-filter', ''), checkbox('check-42', false), input('input-csv-file', '', 'file'), input('llm-api-key', '', 'password')];
const rerenderedResult = region('task-result', '', 'margin-top:20px;display:none');
main.controls = rerendered;
main.regions = [rerenderedResult];
pageState.restorePageState('add-data');
assert.equal(rerendered[0].value, 'https://example.test/annual-report.pdf');
assert.equal(rerendered[1].value, '2023');
assert.equal(rerendered[2].value, 'China');
assert.equal(rerendered[3].checked, true);
assert.equal(rerendered[4].value, '');
assert.equal(rerendered[5].value, '');
assert.equal(rerenderedResult.innerHTML, '<p>抽取到 3 条候选</p>');
assert.equal(rerenderedResult.styleValue, 'margin-top:20px;display:block');

assert.equal(pageState.routeStateKey('stations', { search: 'abc', country: 'China' }), pageState.routeStateKey('stations', { country: 'China', search: 'abc' }));
assert.equal(JSON.stringify(pageState.routeParams({ search: 'abc', __skipRestore: true })), '{"search":"abc"}');
assert.equal(pageState.shouldRestorePageState({}), true);
assert.equal(pageState.shouldRestorePageState({ __skipRestore: true }), false);
console.log('frontend navigation state harness: passed');
