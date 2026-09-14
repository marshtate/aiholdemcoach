const supabaseUrl = 'https://gqzyvfjcfgmocknrnxob.supabase.co';
const supabaseKey = 'sb_publishable_sdYei5FXQLjoe8PKL062Mw_oACuTYYj';
const sb = supabase.createClient(supabaseUrl, supabaseKey);
const authScreen = document.getElementById('auth-screen');
const appScreen = document.getElementById('app-screen');
const logoutBtn = document.getElementById('logout-btn');
const sessionDot = document.getElementById('session-dot');
const appHeader = document.getElementById('app-header');
const modeToggle = document.getElementById('mode-toggle-header');
let currentMode = 'coach';
let cachedHistory = null;

function showApp() {
document.getElementById('bottom-nav').classList.remove('hidden');
appHeader.classList.remove('hidden');
authScreen.classList.add('hidden');
appScreen.classList.remove('hidden');
logoutBtn.classList.remove('hidden');
checkSession();
loadHome();
}
function showAuth() {
document.getElementById('bottom-nav').classList.add('hidden');
appHeader.classList.add('hidden');
authScreen.classList.remove('hidden');
appScreen.classList.add('hidden');
logoutBtn.classList.add('hidden');
modeToggle.classList.add('hidden');
modeToggle.classList.remove('flex');
}
function showError(m) {
const e = document.getElementById('auth-error');
e.textContent = m;
e.classList.remove('hidden');
setTimeout(() => e.classList.add('hidden'), 4000);
}

async function checkSession() {
const { data: { session } } = await sb.auth.getSession();
if (!session) return;
try {
const res = await fetch('/api/sessions', { headers: { 'Authorization': 'Bearer ' + session.access_token } });
const data = await res.json();
const open = (data.sessions || []).find(s => s.status === 'open');
if (open) { sessionDot.className = 'w-3 h-3 bg-emerald-500 rounded-full pulse-green'; }
else { sessionDot.className = 'w-3 h-3 bg-neutral-700 rounded-full'; }
} catch {}
}

document.getElementById('signup-btn').addEventListener('click', async () => {
const email = document.getElementById('email').value, password = document.getElementById('password').value;
if (!email ||!password) { showError('Enter email and password.'); return; }
const { data, error } = await sb.auth.signUp({ email, password });
if (error) { showError(error.message); return; }
if (data.session) showApp(); else showError('Account created. Check email to confirm.');
});
document.getElementById('auth-form').addEventListener('submit', async (ev) => {
ev.preventDefault();
const raw = document.getElementById('email').value, password = document.getElementById('password').value;
if (!raw ||!password) { showError('Enter email and password.'); return; }
let identifier = raw.trim();
if (!identifier.includes('@')) {
    const username = identifier.toLowerCase();
    if (!/^[a-z0-9_]{3,20}$/.test(username)) { showError('That does not look like an email or username.'); return; }
    const r = await fetch('/api/resolve-login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ identifier: username }) });
    const d = await r.json();
    if (d.error) { showError(d.error); return; }
    identifier = d.email;
}
const { data, error } = await sb.auth.signInWithPassword({ email: identifier, password });
if (error) { showError(error.message); return; }
showApp();
});
logoutBtn.addEventListener('click', async () => { await sb.auth.signOut(); showAuth(); });
sb.auth.getSession().then(({ data: { session } }) => { if (session) showApp(); });
const modeCoachBtn = document.getElementById('mode-coach-btn');
const modeTrackBtn = document.getElementById('mode-track-btn');

modeCoachBtn.addEventListener('click', () => {
currentMode = 'coach';
modeCoachBtn.className = modeCoachBtn.className.replace('mode-inactive', 'mode-active');
modeTrackBtn.className = modeTrackBtn.className.replace('mode-active', 'mode-inactive');
resetChat();
});
modeTrackBtn.addEventListener('click', () => {
currentMode = 'track';
modeTrackBtn.className = modeTrackBtn.className.replace('mode-inactive', 'mode-active');
modeCoachBtn.className = modeCoachBtn.className.replace('mode-active', 'mode-inactive');
resetChat();
});

function resetChat() {
const chatbox = document.getElementById('chatbox');
const intro = currentMode === 'coach'? 'Send me any hand - your cards, the board, your position - and I\'ll give you a real read.': 'Log a hand - what you played, where, what happened. When you\'re done for the night, tell me how you did - up $40, down $12 - and I\'ll close it out.';
chatbox.innerHTML = `<div class="flex items-start"><div class="bg-[#1a1a1a] text-gray-200 px-4 py-2.5 rounded-2xl rounded-tl-sm text-sm max-w-[85%] shadow-sm">${intro}</div></div>`;
document.getElementById('user-input').placeholder = currentMode === 'coach'? 'Type your hand...': 'Log your hand...';
}

const tabHome = document.getElementById('tab-home');
const tabChat = document.getElementById('tab-chat');
const tabHistory = document.getElementById('tab-history');
const tabStats = document.getElementById('tab-stats');
const tabSocial = document.getElementById('tab-social');
const homeView = document.getElementById('home-view');
const chatView = document.getElementById('chat-view');
const historyView = document.getElementById('history-view');
const statsView = document.getElementById('stats-view');
const socialView = document.getElementById('social-view');

function setActiveTab(active) {
tabs = [tabHome, tabChat, tabHistory, tabStats, tabSocial];
views = [homeView, chatView, historyView, statsView, socialView];
tabs.forEach(t => {
const icon = t.querySelector('.nav-icon');
const label = t.querySelector('span');
icon.classList.remove('text-emerald-400'); icon.classList.add('text-gray-500');
label.classList.remove('text-emerald-400'); label.classList.add('text-gray-500');
});
views.forEach(v => v.classList.add('hidden'));
const aIcon = active.querySelector('.nav-icon');
const aLabel = active.querySelector('span');
aIcon.classList.remove('text-gray-500'); aIcon.classList.add('text-emerald-400');
aLabel.classList.remove('text-gray-500'); aLabel.classList.add('text-emerald-400');
if (active === tabHome) homeView.classList.remove('hidden');
if (active === tabChat) chatView.classList.remove('hidden');
if (active === tabHistory) historyView.classList.remove('hidden');
if (active === tabStats) statsView.classList.remove('hidden');
if (active === tabSocial) socialView.classList.remove('hidden');
const toggle = document.getElementById('mode-toggle-header');
if (active === tabChat) { toggle.classList.remove('hidden'); toggle.classList.add('flex'); }
else { toggle.classList.add('hidden'); toggle.classList.remove('flex'); }
}
tabHome.addEventListener('click', () => { setActiveTab(tabHome); homeView.classList.remove('hidden'); loadHome(); });
tabChat.addEventListener('click', () => { setActiveTab(tabChat); chatView.classList.remove('hidden'); });
tabHistory.addEventListener('click', () => { setActiveTab(tabHistory); historyView.classList.remove('hidden'); loadHistory(); });
tabStats.addEventListener('click', () => { setActiveTab(tabStats); statsView.classList.remove('hidden'); loadStats(); });
tabSocial.addEventListener('click', () => { setActiveTab(tabSocial); socialView.classList.remove('hidden'); loadSocial(); });
function tierClass(t) {
if (!t) return 'tier-speculative';
const l = t.toLowerCase();
if (l === 'premium') return 'tier-premium';
if (l === 'strong') return 'tier-strong';
if (l === 'playable') return 'tier-playable';
if (l === 'speculative') return 'tier-speculative';
if (l === 'trash') return 'tier-trash';
return 'tier-speculative';
}

async function fetchHistory() {
if (cachedHistory) return cachedHistory;
const { data: { session } } = await sb.auth.getSession();
if (!session) return [];
try {
const res = await fetch('/api/history', { headers: { 'Authorization': 'Bearer ' + session.access_token } });
const data = await res.json();
cachedHistory = data.history || [];
return cachedHistory;
} catch { return []; }
}

async function fetchSessions() {
const { data: { session } } = await sb.auth.getSession();
if (!session) return [];
try {
const res = await fetch('/api/sessions', { headers: { 'Authorization': 'Bearer ' + session.access_token } });
const data = await res.json();
return data.sessions || [];
} catch { return []; }
}

async function loadHome() {
const entries = await fetchHistory();
const sessions = await fetchSessions();
const el = document.getElementById('home-view');
if (entries.length === 0 && sessions.length === 0) {
el.innerHTML = '<div class="text-center py-12 space-y-2"><p class="text-lg font-semibold">No data yet.</p><p class="text-sm text-gray-500">Switch to Track and log a hand to get started.</p></div>';
return;
}

const open = sessions.find(s => s.status === 'open');
const closed = sessions.filter(s => s.status === 'closed' && s.profit!== null);
let folds = 0;
entries.forEach(e => { if (e.player_action && e.player_action.toLowerCase() === 'fold') folds++; });
const foldPct = entries.length > 0? Math.round((folds / entries.length) * 100): 0;
const totalProfit = closed.reduce((sum, s) => sum + (s.profit || 0), 0);
const profitStr = totalProfit >= 0? '+$' + totalProfit.toFixed(2): '-$' + Math.abs(totalProfit).toFixed(2);
const wins = closed.filter(s => s.profit > 0).length;
const winRate = closed.length > 0? Math.round((wins / closed.length) * 100): null;

let html = '';

if (open) {
html += `<div class="bg-emerald-900/30 border border-emerald-800 rounded-xl p-4 space-y-1">
<div class="flex items-center gap-2"><div class="w-2 h-2 bg-emerald-500 rounded-full pulse-green"></div><span class="text-xs font-semibold text-emerald-400">Session open</span></div>
<p class="text-xs text-gray-500">Log hands. When you're done, tell me your profit or loss.</p>
</div>`;
}

html += `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-2">
<h3 class="text-sm font-semibold text-gray-300">Overview</h3>
<div class="grid grid-cols-2 gap-3">
<div class="bg-black rounded-lg p-3 text-center">
<p class="text-xl font-bold text-emerald-400">${entries.length}</p>
<p class="text-xs text-gray-500">Hands</p>
</div>
<div class="bg-black rounded-lg p-3 text-center">
<p class="text-xl font-bold text-gray-300">${foldPct}%</p>
<p class="text-xs text-gray-500">Fold rate</p>
</div>
</div>
</div>`;

if (closed.length > 0) {
html += `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-2">
<h3 class="text-sm font-semibold text-gray-300">Sessions</h3>
<div class="grid grid-cols-2 gap-3">
<div class="bg-black rounded-lg p-3 text-center">
<p class="text-xl font-bold text-emerald-400">${closed.length}</p>
<p class="text-xs text-gray-500">Played</p>
</div>
<div class="bg-black rounded-lg p-3 text-center">
<p class="text-xl font-bold ${totalProfit >= 0? 'text-emerald-400': 'text-red-400'}">${profitStr}</p>
<p class="text-xs text-gray-500">Total profit</p>
</div>
<div class="bg-black rounded-lg p-3 text-center">
<p class="text-xl font-bold text-amber-400">${winRate!== null? winRate + '%': '-'}</p>
<p class="text-xs text-gray-500">Win rate</p>
</div>
<div class="bg-black rounded-lg p-3 text-center">
<p class="text-xl font-bold ${totalProfit >= 0? 'text-emerald-400': 'text-red-400'}">${closed.length > 0? (totalProfit >= 0? '+': '') + '$' + (totalProfit / closed.length).toFixed(2): '-'}</p>
<p class="text-xs text-gray-500">Avg per night</p>
</div>
</div>
</div>`;

const recent = closed.slice(0, 5).reverse();
html += `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-3">
<h3 class="text-sm font-semibold text-gray-300">Recent nights</h3>
${recent.map(s => {
const d = new Date(s.closed_at || s.created_at).toLocaleDateString();
const p = s.profit || 0;
return `<div class="flex justify-between items-center text-xs">
<span class="text-gray-400">${d}</span>
<span class="font-semibold ${p >= 0? 'text-emerald-400': 'text-red-400'}">${p >= 0? '+': ''}$${p.toFixed(2)}</span>
</div>`;
}).join('')}
</div>`;
}

el.innerHTML = html;
}
async function loadHistory() {
const entries = await fetchHistory();
const el = document.getElementById('history-view');
if (entries.length === 0) { el.innerHTML = '<p class="text-sm text-gray-500 text-center py-8">No hands yet.</p>'; return; }
el.innerHTML = entries.map(e => {
let top = '<div class="flex items-center gap-2 flex-wrap">';
if (e.hand) top += `<span class="text-sm font-bold text-emerald-400">${e.hand}</span>`;
if (e.tier) top += `<span class="text-xs font-semibold px-2 py-0.5 rounded ${tierClass(e.tier)} text-white capitalize">${e.tier}</span>`;
if (e.position) top += `<span class="text-xs text-gray-500">${e.position}</span>`;
if (e.player_action) top += `<span class="text-xs font-semibold text-gray-300">${e.player_action}</span>`;
top += `<span class="text-xs text-gray-600 ml-auto">${new Date(e.created_at).toLocaleDateString()}</span></div>`;
let resultHTML = '';
if (e.result) {
resultHTML = `<div class="flex items-center gap-2 pt-1 border-t border-neutral-800 mt-1">
<span class="text-xs font-semibold ${e.result === 'won'? 'text-emerald-400': 'text-red-400'}">${e.result === 'won'? 'Won': 'Lost'}</span>
${e.amount? `<span class="text-xs ${e.result === 'won'? 'text-emerald-400': 'text-red-400'}">$${e.amount.toFixed(2)}</span>`: ''}
</div>`;
}
return `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-2">${top}<p class="text-sm text-gray-300">${e.reply}</p>${resultHTML}</div>`;
}).join('');
}

async function loadStats() {
const entries = await fetchHistory();
const sessions = await fetchSessions();
const el = document.getElementById('stats-view');
if (entries.length === 0 && sessions.length === 0) { el.innerHTML = '<p class="text-sm text-gray-500 text-center py-8">No data yet.</p>'; return; }

const tiers = {}, hands = {}, actions = {};
let folds = 0;
entries.forEach(e => {
if (e.tier) { const k = e.tier.toLowerCase(); tiers[k] = (tiers[k] || 0) + 1; }
if (e.hand) { hands[e.hand] = (hands[e.hand] || 0) + 1; }
if (e.player_action) { const a = e.player_action.toLowerCase(); actions[a] = (actions[a] || 0) + 1; if (a === 'fold') folds++; }
});

const foldPct = entries.length > 0? Math.round((folds / entries.length) * 100): 0;
const closed = sessions.filter(s => s.status === 'closed' && s.profit!== null);
const open = sessions.find(s => s.status === 'open');
const totalProfit = closed.reduce((sum, s) => sum + (s.profit || 0), 0);
const wins = closed.filter(s => s.profit > 0).length;
const winRate = closed.length > 0? Math.round((wins / closed.length) * 100): null;
const profitStr = totalProfit >= 0? '+$' + totalProfit.toFixed(2): '-$' + Math.abs(totalProfit).toFixed(2);
const avgProfit = closed.length > 0? (totalProfit / closed.length): 0;
const avgStr = avgProfit >= 0? '+$' + avgProfit.toFixed(2): '-$' + Math.abs(avgProfit).toFixed(2);

let html = '';
if (open) {
html += `<div class="bg-emerald-900/30 border border-emerald-800 rounded-xl p-4 space-y-1">
<div class="flex items-center gap-2"><div class="w-2 h-2 bg-emerald-500 rounded-full pulse-green"></div><span class="text-xs font-semibold text-emerald-400">Session open</span></div>
<p class="text-xs text-gray-500">Log hands. When you're done, tell me your profit or loss.</p>
</div>`;
}
html += `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-2">
<h3 class="text-sm font-semibold text-gray-300">Overview</h3>
<div class="grid grid-cols-2 gap-3">
<div class="bg-black rounded-lg p-3 text-center"><p class="text-xl font-bold text-emerald-400">${entries.length}</p><p class="text-xs text-gray-500">Hands</p></div>
<div class="bg-black rounded-lg p-3 text-center"><p class="text-xl font-bold text-gray-300">${foldPct}%</p><p class="text-xs text-gray-500">Fold rate</p></div>
</div>
</div>`;

if (closed.length > 0) {
html += `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-2">
<h3 class="text-sm font-semibold text-gray-300">Sessions</h3>
<div class="grid grid-cols-2 gap-3">
<div class="bg-black rounded-lg p-3 text-center"><p class="text-xl font-bold text-emerald-400">${closed.length}</p><p class="text-xs text-gray-500">Played</p></div>
<div class="bg-black rounded-lg p-3 text-center"><p class="text-xl font-bold ${totalProfit >= 0? 'text-emerald-400': 'text-red-400'}">${profitStr}</p><p class="text-xs text-gray-500">Total profit</p></div>
<div class="bg-black rounded-lg p-3 text-center"><p class="text-xl font-bold text-amber-400">${winRate}%</p><p class="text-xs text-gray-500">Win rate</p></div>
<div class="bg-black rounded-lg p-3 text-center"><p class="text-xl font-bold ${avgProfit >= 0? 'text-emerald-400': 'text-red-400'}">${avgStr}</p><p class="text-xs text-gray-500">Avg per night</p></div>
</div>
</div>`;
const recent = closed.slice(0, 5).reverse();
html += `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-3">
<h3 class="text-sm font-semibold text-gray-300">Recent nights</h3>
${recent.map(s => {
const d = new Date(s.closed_at || s.created_at).toLocaleDateString();
const p = s.profit || 0;
return `<div class="flex justify-between items-center text-xs"><span class="text-gray-400">${d}</span><span class="font-semibold ${p >= 0? 'text-emerald-400': 'text-red-400'}">${p >= 0? '+': ''}$${p.toFixed(2)}</span></div>`;
}).join('')}
</div>`;
} else {
html += `<div class="bg-[#1a1a1a] rounded-xl p-4"><p class="text-sm text-gray-500 text-center">Track a session and close it to see your nights.</p></div>`;
}

const topHands = Object.entries(hands).sort((a, b) => b[1] - a[1]).slice(0, 5);
if (topHands.length > 0) {
const maxH = topHands[0][1];
html += `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-3">
<h3 class="text-sm font-semibold text-gray-300">Most studied</h3>
${topHands.map(([h, c]) => `<div class="space-y-1"><div class="flex justify-between text-xs"><span class="text-emerald-400 font-bold">${h}</span><span class="text-gray-500">${c}</span></div><div class="w-full bg-black rounded-full"><div class="bar bg-emerald-500" style="width: ${Math.round((c / maxH) * 100)}%"></div></div></div>`).join('')}
</div>`;
}

const actionOrder = ['fold', 'call', 'raise', '3-bet', 'check', 'all-in'];
const actionColors = { fold: 'bg-gray-500', call: 'bg-blue-500', raise: 'bg-emerald-500', '3-bet': 'bg-purple-500', check: 'bg-gray-400', 'all-in': 'bg-red-500' };
const actionEntries = actionOrder.filter(a => actions[a]);
if (actionEntries.length > 0) {
const maxA = Math.max(...actionEntries.map(a => actions[a]));
html += `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-3">
<h3 class="text-sm font-semibold text-gray-300">Actions</h3>
${actionEntries.map(a => `<div class="space-y-1"><div class="flex justify-between text-xs"><span class="capitalize text-gray-300">${a}</span><span class="text-gray-500">${actions[a]}</span></div><div class="w-full bg-black rounded-full"><div class="bar ${actionColors[a] || 'bg-gray-500'}" style="width: ${Math.round((actions[a] / maxA) * 100)}%"></div></div></div>`).join('')}
</div>`;
}
el.innerHTML = html;
}
async function logResult(entryId, result) {
const { data: { session } } = await sb.auth.getSession();
if (!session) return;
const amtInput = document.getElementById('amt-' + entryId);
const amount = amtInput && amtInput.value? parseFloat(amtInput.value): null;
try {
await fetch('/api/result', {
method: 'POST',
headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + session.access_token },
body: JSON.stringify({ id: entryId, result, amount })
});
cachedHistory = null;
loadHistory();
} catch {}
}

const chatbox = document.getElementById('chatbox');
const input = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');

function appendMessage(text, isUser) {
const w = document.createElement('div'); w.className = isUser? 'flex justify-end': 'flex justify-start';
const b = document.createElement('div');
b.className = isUser? 'bg-emerald-600 text-white px-4 py-2.5 rounded-2xl rounded-tr-sm text-sm max-w-[85%] shadow-sm break-words whitespace-pre-wrap': 'bg-[#1a1a1a] text-gray-200 px-4 py-2.5 rounded-2xl rounded-tl-sm text-sm max-w-[85%] shadow-sm break-words whitespace-pre-wrap';
b.textContent = text; w.appendChild(b); chatbox.appendChild(w); chatbox.scrollTop = chatbox.scrollHeight; return b;
}

async function sendMessage(e) {
e.preventDefault(); const text = input.value.trim(); if (!text) return;
appendMessage(text, true); input.value = ''; input.disabled = true; sendBtn.disabled = true;
const lb = appendMessage('...', false);
const { data: { session } } = await sb.auth.getSession();
try {
const h = {'Content-Type': 'application/json'}; if (session) h['Authorization'] = 'Bearer ' + session.access_token;
const res = await fetch('/api/chat', { method: 'POST', headers: h, body: JSON.stringify({ message: text, mode: currentMode }) });
const data = await res.json();
lb.textContent = data.reply || data.error || 'No response.';
if (data.reply && data.reply.includes('Session closed')) {
checkSession();
cachedHistory = null;
} else {
cachedHistory = null;
}
} catch { lb.textContent = 'Error: Could not reach the server.'; }
finally { input.disabled = false; sendBtn.disabled = false; input.blur(); setTimeout(() => { chatbox.scrollTop = chatbox.scrollHeight; }, 100); }
}
var nav = document.getElementById('bottom-nav');
var kbInput = document.getElementById('user-input');
var kbFooter = document.getElementById('chat-footer');
function hideNav() { nav.classList.add('hidden'); kbFooter.classList.add('kb-open'); }
function showNav() { nav.classList.remove('hidden'); kbFooter.classList.remove('kb-open'); }
kbInput.addEventListener('focus', hideNav);
kbInput.addEventListener('blur', function() { setTimeout(showNav, 250); });

async function authedFetch(path, opts) {
const { data: { session } } = await sb.auth.getSession();
if (!session) return null;
const headers = { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + session.access_token };
const res = await fetch(path, Object.assign({ headers: headers }, opts || {}));
return res.json();
}
function money(x) {
if (x === null || x === undefined) return '-';
const v = Math.round(x * 100) / 100;
return (v >= 0 ? '+' : '') + '$' + v.toFixed(2);
}
function statGrid(stats, omitBest) {
if (!stats || stats.nights === 0) return '<p class="text-xs text-gray-500 text-center py-4">No completed sessions yet.</p>';
let html = '<div class="grid grid-cols-2 gap-2">';
const winRate = stats.win_rate === null ? '-' : stats.win_rate + '%';
html += `<div class="bg-black rounded-lg p-3 text-center"><p class="text-xl font-bold text-emerald-400">${stats.nights}</p><p class="text-xs text-gray-500">Nights</p></div>`;
html += `<div class="bg-black rounded-lg p-3 text-center"><p class="text-xl font-bold ${stats.total_profit >= 0 ? 'text-emerald-400' : 'text-red-400'}">${money(stats.total_profit)}</p><p class="text-xs text-gray-500">Total profit</p></div>`;
html += `<div class="bg-black rounded-lg p-3 text-center"><p class="text-xl font-bold text-amber-400">${winRate}</p><p class="text-xs text-gray-500">Win rate</p></div>`;
html += `<div class="bg-black rounded-lg p-3 text-center"><p class="text-xl font-bold ${stats.avg_profit >= 0 ? 'text-emerald-400' : 'text-red-400'}">${money(stats.avg_profit)}</p><p class="text-xs text-gray-500">Avg / night</p></div>`;
if (!omitBest) {
html += `<div class="bg-black rounded-lg p-3 text-center"><p class="text-xl font-bold text-gray-300">${money(stats.best_night)}</p><p class="text-xs text-gray-500">Best night</p></div>`;
html += `<div class="bg-black rounded-lg p-3 text-center"><p class="text-xl font-bold text-gray-300">${stats.streak}</p><p class="text-xs text-gray-500">Win streak</p></div>`;
}
html += '</div>';
return html;
}
let mySocial = null;
async function loadSocial() {
const el = document.getElementById('social-view');
el.innerHTML = '<p class="text-sm text-gray-500 text-center py-8">Loading...</p>';
const data = await authedFetch('/api/friends');
if (!data || data.error) { el.innerHTML = '<p class="text-sm text-red-400 text-center py-8">' + ((data && data.error) || 'Could not load.') + '</p>'; return; }
mySocial = data;
let html = '';
html += `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-2">
<div class="flex items-center justify-between">
<h3 class="text-sm font-semibold text-gray-300">You</h3>
<button onclick="setUsername()" class="text-xs text-gray-400 hover:text-emerald-400">edit</button>
</div>
<p class="text-sm text-emerald-400 font-bold">${data.username}</p>
${statGrid(data.stats)}
</div>`;
html += `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-2">
<h3 class="text-sm font-semibold text-gray-300">Add a friend</h3>
<div class="flex items-center gap-2">
<input id="friend-username" type="text" placeholder="Username" class="flex-1 bg-black text-gray-100 text-sm rounded-lg px-3 py-2.5 outline-none focus:ring-2 focus:ring-emerald-500 border border-neutral-800 placeholder-gray-600" />
<button onclick="sendFriendRequest()" class="bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold px-4 py-2.5 rounded-lg transition">Add</button>
</div>
<p id="friend-error" class="text-xs text-red-400 hidden"></p>
</div>`;
if (data.incoming && data.incoming.length > 0) {
html += `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-2">
<h3 class="text-sm font-semibold text-gray-300">Friend requests</h3>
${data.incoming.map(u => `<div class="flex items-center justify-between text-sm">
<span class="text-gray-200">${u.username}</span>
<button onclick="friendAction('${u.user_id}', 'accept')" class="bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition">Accept</button>
</div>`).join('')}
</div>`;
}
if (data.outgoing && data.outgoing.length > 0) {
html += `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-2">
<h3 class="text-sm font-semibold text-gray-300">Pending sent</h3>
${data.outgoing.map(u => `<div class="flex items-center justify-between text-sm"><span class="text-gray-500">${u.username}</span><span class="text-xs text-gray-600">requested</span></div>`).join('')}
</div>`;
}
html += `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-2">
<h3 class="text-sm font-semibold text-gray-300">Friends</h3>
${data.friends && data.friends.length > 0 ? data.friends.map(u => `<div class="flex items-center justify-between text-sm gap-2">
<button onclick="viewProfile('${u.username}')" class="text-gray-200 hover:text-emerald-400 text-left font-medium">${u.username}</button>
<button onclick="friendAction('${u.user_id}', 'remove')" class="text-xs text-gray-500 hover:text-red-400">remove</button>
</div>`).join('') : '<p class="text-sm text-gray-500 text-center py-3">No friends yet. Add one by username above.</p>'}
</div>`;
html += `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-2">
<h3 class="text-sm font-semibold text-gray-300">Friend leaderboard</h3>
<p class="text-xs text-gray-500">Ranks you and your friends by total profit. Sessions only - no hand data is shared.</p>
<div id="leaderboard-holder"></div>
</div>`;
el.innerHTML = html;
loadLeaderboard();
}
async function loadLeaderboard() {
const holder = document.getElementById('leaderboard-holder');
if (!holder) return;
const data = await authedFetch('/api/leaderboard');
if (!data || data.error) { holder.innerHTML = '<p class="text-xs text-red-400 py-2">' + ((data && data.error) || 'Could not load.') + '</p>'; return; }
const rows = data.leaderboard || [];
if (rows.length === 0) { holder.innerHTML = '<p class="text-xs text-gray-500 py-2">No completed sessions among your friends yet.</p>'; return; }
holder.innerHTML = rows.map(r => `<div class="flex items-center justify-between text-sm py-1 ${r.you ? 'text-emerald-400' : 'text-gray-300'}">
<span class="font-semibold">${r.rank}. ${r.username}${r.you ? ' (you)' : ''}</span>
<span class="font-mono ${r.total_profit >= 0 ? 'text-emerald-400' : 'text-red-400'}">${money(r.total_profit)}</span>
</div>`).join('');
}
async function sendFriendRequest() {
const input = document.getElementById('friend-username');
const err = document.getElementById('friend-error');
const username = input.value.trim().toLowerCase();
if (!username) return;
err.classList.add('hidden');
const data = await authedFetch('/api/friend-request', { method: 'POST', body: JSON.stringify({ username: username }) });
if (data && data.error) { err.textContent = data.error; err.classList.remove('hidden'); return; }
input.value = '';
loadSocial();
}
async function friendAction(friendId, action) {
const data = await authedFetch('/api/friend-action', { method: 'POST', body: JSON.stringify({ action: action, friend_id: friendId }) });
if (data && data.error) { alert(data.error); return; }
loadSocial();
}
async function setUsername() {
const current = mySocial ? mySocial.username : '';
const next = prompt('Your public username (3-20 chars, letters/numbers/underscore):', current || '');
if (!next) return;
const clean = next.trim().toLowerCase();
if (!/^[a-z0-9_]{3,20}$/.test(clean)) { alert('Usernames are 3-20 letters, numbers, or underscores.'); return; }
const data = await authedFetch('/api/username', { method: 'POST', body: JSON.stringify({ username: clean }) });
if (data && data.error) { alert(data.error); return; }
loadSocial();
}
async function viewProfile(username) {
const el = document.getElementById('social-view');
el.innerHTML = '<p class="text-sm text-gray-500 text-center py-8">Loading...</p>';
const data = await authedFetch('/api/profile?username=' + encodeURIComponent(username));
if (!data || data.error) { el.innerHTML = '<p class="text-sm text-red-400 text-center py-8">' + ((data && data.error) || 'Could not load.') + '</p>'; return; }
const theirs = data.profile;
const mine = mySocial ? mySocial.stats : null;
let html = `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-2">
<button onclick="loadSocial()" class="text-xs text-gray-400 hover:text-emerald-400">&larr; Back</button>
<div class="flex items-center justify-between pt-1">
<div><h3 class="text-sm font-semibold text-gray-300">${theirs.username}</h3></div>
<div><h3 class="text-sm font-semibold text-gray-300">You</h3></div>
</div>
${statGrid(theirs.stats, true)}
${mine ? statGrid(mine, true) : ''}
</div>`;
el.innerHTML = html;
}