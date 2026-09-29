const $ = (selector) => document.querySelector(selector);
let busy = false;
const bytes = (value) => value >= 1073741824 ? (value / 1073741824).toFixed(2) + ' GB' : (value / 1048576).toFixed(1) + ' MB';
function message(text, error = false) { $('#message').textContent = text; $('#message').className = error ? 'error' : ''; }
async function api(path, payload) {
  const response = await fetch(path, payload ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) } : {});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '请求失败，请重试。');
  return result;
}
async function change(action, name) {
  if (busy) return;
  if (action === 'disable' && !confirm(`停用 ${name} 会立即断开该配置。确认这不是你当前用于打开管理页的连接？`)) return;
  busy = true;
  try { await api('/api/' + action, { name }); message(action === 'add' ? '配置已生成，请在下方下载或扫码。' : '状态已更新。'); await refresh(); }
  catch (error) { message(error.message, true); }
  finally { busy = false; }
}
function button(text, cls, callback) { const el = document.createElement('button'); el.textContent = text; el.className = cls; el.onclick = callback; return el; }
async function refresh() {
  try {
    const data = await api('/api/status');
    $('#verification').textContent = data.note;
    $('#count').textContent = data.devices.length;
    $('#recent').textContent = data.devices.filter(d => d.enabled && d.last_handshake > Date.now() / 1000 - 180).length;
    $('#traffic').textContent = bytes(data.devices.reduce((sum, d) => sum + d.received_bytes + d.sent_bytes, 0));
    const container = $('#devices'); container.replaceChildren();
    for (const device of data.devices) {
      const row = document.createElement('div'); row.className = 'device';
      const info = document.createElement('div'); const name = document.createElement('span'); name.className = 'device-name'; name.textContent = device.name;
      const state = document.createElement('span'); state.className = 'pill' + (device.enabled ? '' : ' disabled'); state.textContent = device.enabled ? '已启用' : '已停用';
      const meta = document.createElement('div'); meta.className = 'device-meta';
      meta.textContent = `最近握手：${device.last_handshake ? new Date(device.last_handshake * 1000).toLocaleString() : '尚未连接'} · 设备上传 ${bytes(device.received_bytes)} / 下载 ${bytes(device.sent_bytes)}`;
      info.append(name, state, meta); const actions = document.createElement('div'); actions.className = 'actions';
      const download = document.createElement('a'); download.className = 'download'; download.textContent = '下载配置'; download.href = `/api/profile/${device.name}.conf`;
      actions.append(download, button('二维码', 'secondary', () => { $('#qr-title').textContent = device.name + ' · 扫码导入'; $('#qr-image').src = `/api/profile/${device.name}.png`; $('#qr').showModal(); }), button(device.enabled ? '停用' : '启用', device.enabled ? 'danger' : '', () => change(device.enabled ? 'disable' : 'enable', device.name)));
      row.append(info, actions); container.append(row);
    }
  } catch (error) { message(error.message, true); }
}
$('#add').onsubmit = async event => { event.preventDefault(); const name = $('#name').value.trim(); await change('add', name); };
$('#refresh').onclick = refresh;
$('#close-qr').onclick = () => { $('#qr').close(); $('#qr-image').removeAttribute('src'); };
refresh(); setInterval(() => { if (!busy) refresh(); }, 10000);
