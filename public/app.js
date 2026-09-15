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
let recapActive = false;
let recapSessionId = null;
const settingsBtn = document.getElementById('settings-btn');
let currentTheme = localStorage.getItem('aihc_theme') || 'dark';
let currentUnits = localStorage.getItem('aihc_units') || 'dollars';
let currentDefaultBuyin = localStorage.getItem('aihc_default_buyin') === null ? '5' : localStorage.getItem('aihc_default_buyin');
function seg(el, on) {
if (!el) return;
if (on) el.className = el.className.replace('mode-inactive', 'mode-active');
else el.className = el.className.replace('mode-active', 'mode-inactive');
}
function refreshSettingsUI() {
seg(document.getElementById('theme-dark-btn'), currentTheme === 'dark');
seg(document.getElementById('theme-light-btn'), currentTheme === 'light');
seg(document.getElementById('unit-dollars-btn'), currentUnits === 'dollars');
seg(document.getElementById('unit-bb-btn'), currentUnits === 'bb');
seg(document.getElementById('unit-chips-btn'), currentUnits === 'chips');
const db = document.getElementById('default-buyin');
if (db) db.value = currentDefaultBuyin;
}
function setDefaultBuyin(v) {
const val = v === '' || v === null ? '' : String(parseFloat(v));
currentDefaultBuyin = val;
localStorage.setItem('aihc_default_buyin', val);
}
async function exportMyData() {
const data = await authedFetch('/api/export');
if (!data || data.error) { alert((data && data.error) || 'Could not export your data.'); return; }
const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
const url = URL.createObjectURL(blob);
const a = document.createElement('a');
a.href = url;
a.download = 'ai-holdem-coach-export.json';
document.body.appendChild(a);
a.click();
URL.revokeObjectURL(url);
a.remove();
}
async function deleteMyAccount() {
const check = prompt('This permanently deletes every hand, session, and stat. Type DELETE to confirm:');
if (check === null) return;
if ((check || '').trim().toLowerCase() !== 'delete') { alert('Not confirmed - your account was not deleted.'); return; }
const res = await authedFetch('/api/account/delete', { method: 'POST', body: JSON.stringify({ confirm: 'delete' }) });
if (res && res.error) { alert(res.error); return; }
try { await sb.auth.signOut(); } catch (e) {}
showAuth();
closeSettings();
alert('Your account and all data have been deleted. Goodbye!');
}
function applyTheme() {
document.documentElement.setAttribute('data-theme', currentTheme);
localStorage.setItem('aihc_theme', currentTheme);
const meta = document.querySelector('meta[name="theme-color"]');
if (meta) meta.setAttribute('content', currentTheme === 'light' ? '#f4f4f5' : '#000000');
}
function setTheme(t) { currentTheme = t; applyTheme(); refreshSettingsUI(); }
function unitAmount(v) {
if (v === null || v === undefined) return '';
if (currentUnits === 'bb') return v.toFixed(2) + 'bb';
if (currentUnits === 'chips') return Math.round(v) + ' chips';
return '$' + v.toFixed(2);
}
function setUnits(u) {
currentUnits = u;
localStorage.setItem('aihc_units', u);
refreshSettingsUI();
renderQuickChips();
if (cachedHistory) renderHandList();
}
function openSettings() {
refreshSettingsUI();
const m = document.getElementById('settings-modal');
m.classList.remove('hidden');
m.classList.add('flex', 'items-center', 'justify-center');
}
function closeSettings() {
const m = document.getElementById('settings-modal');
m.classList.add('hidden');
m.classList.remove('flex', 'items-center', 'justify-center');
}
applyTheme();
refreshSettingsUI();
settingsBtn.addEventListener('click', openSettings);

function showApp() {
const splash = document.getElementById('splash');
if (splash) splash.classList.add('hidden');
document.getElementById('bottom-nav').classList.remove('hidden');
appHeader.classList.remove('hidden');
authScreen.classList.add('hidden');
appScreen.classList.remove('hidden');
logoutBtn.classList.remove('hidden');
settingsBtn.classList.remove('hidden');
checkSession();
loadHome();
showOnboarding();
}
function showAuth() {
const splash = document.getElementById('splash');
if (splash) splash.classList.add('hidden');
document.getElementById('bottom-nav').classList.add('hidden');
appHeader.classList.add('hidden');
authScreen.classList.remove('hidden');
appScreen.classList.add('hidden');
logoutBtn.classList.add('hidden');
settingsBtn.classList.add('hidden');
modeToggle.classList.add('hidden');
modeToggle.classList.remove('flex');
}
function showError(m) {
const e = document.getElementById('auth-error');
e.textContent = m;
e.classList.remove('hidden');
setTimeout(() => e.classList.add('hidden'), 4000);
}
function showNotice(m) {
const e = document.getElementById('auth-notice');
e.textContent = m;
e.classList.remove('hidden');
setTimeout(() => e.classList.add('hidden'), 6000);
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
document.getElementById('forgot-btn').addEventListener('click', () => {
document.getElementById('auth-form').classList.add('hidden');
document.getElementById('forgot-form').classList.remove('hidden');
});
document.getElementById('forgot-back').addEventListener('click', () => {
document.getElementById('auth-form').classList.remove('hidden');
document.getElementById('forgot-form').classList.add('hidden');
});
document.getElementById('send-reset-btn').addEventListener('click', async () => {
const email = document.getElementById('forgot-email').value.trim();
if (!email || !email.includes('@')) { showError('Enter your email.'); return; }
const { error } = await sb.auth.resetPasswordForEmail(email, { redirectTo: window.location.origin });
if (error) { showError(error.message); return; }
document.getElementById('forgot-form').classList.add('hidden');
document.getElementById('auth-form').classList.remove('hidden');
showNotice('Reset link sent. Check your email.');
});
function showResetPanel() {
document.getElementById('bottom-nav').classList.add('hidden');
appHeader.classList.add('hidden');
authScreen.classList.remove('hidden');
appScreen.classList.add('hidden');
logoutBtn.classList.add('hidden');
settingsBtn.classList.add('hidden');
modeToggle.classList.add('hidden');
modeToggle.classList.remove('flex');
document.getElementById('auth-form').classList.add('hidden');
document.getElementById('auth-error').classList.add('hidden');
document.getElementById('reset-panel').classList.remove('hidden');
}
document.getElementById('reset-submit-btn').addEventListener('click', async () => {
const p1 = document.getElementById('new-password').value;
const p2 = document.getElementById('new-password-2').value;
if (p1.length < 6) { showError('Password must be at least 6 characters.'); return; }
if (p1 !== p2) { showError('Passwords don\'t match.'); return; }
const { error } = await sb.auth.updateUser({ password: p1 });
if (error) { showError(error.message); return; }
history.replaceState(null, '', window.location.pathname + window.location.search);
document.getElementById('reset-panel').classList.add('hidden');
document.getElementById('auth-form').classList.remove('hidden');
showNotice('Password updated. Sign in with your new password.');
});
logoutBtn.addEventListener('click', async () => { await sb.auth.signOut(); showAuth(); });
function onbLoaded() { return localStorage.getItem('onboarded'); }
function showOnboarding() {
if (onbLoaded()) return;
document.getElementById('onboarding').classList.remove('hidden');
document.getElementById('onboarding').classList.add('flex');
}
function hideOnboarding() {
localStorage.setItem('onboarded', '1');
const o = document.getElementById('onboarding');
o.classList.add('hidden');
o.classList.remove('flex');
}
document.getElementById('onb-done-btn').addEventListener('click', hideOnboarding);
function isRecovery() { return (window.location.hash || '').includes('type=recovery'); }
sb.auth.onAuthStateChange((event, session) => {
if (event === 'PASSWORD_RECOVERY') {
window.history.replaceState(null, '', window.location.pathname);
showResetPanel();
}
if (event === 'SIGNED_OUT') { showAuth(); }
});
handleDiscordCallback();
sb.auth.getSession().then(({ data: { session } }) => { if (session && !isRecovery()) showApp(); else { const splash = document.getElementById('splash'); if (splash) splash.classList.add('hidden'); } });
if ('serviceWorker' in navigator) { navigator.serviceWorker.register('/sw.js').catch(function() {}); }
const modeCoachBtn = document.getElementById('mode-coach-btn');
const modeTrackBtn = document.getElementById('mode-track-btn');

modeCoachBtn.addEventListener('click', () => {
currentMode = 'coach';
recapActive = false;
modeCoachBtn.className = modeCoachBtn.className.replace('mode-inactive', 'mode-active');
modeTrackBtn.className = modeTrackBtn.className.replace('mode-active', 'mode-inactive');
resetChat();
});
modeTrackBtn.addEventListener('click', () => {
currentMode = 'track';
recapActive = false;
modeTrackBtn.className = modeTrackBtn.className.replace('mode-inactive', 'mode-active');
modeCoachBtn.className = modeCoachBtn.className.replace('mode-active', 'mode-inactive');
resetChat();
});

function resetChat() {
const chatbox = document.getElementById('chatbox');
const intro = currentMode === 'coach'? 'Send me any hand - your cards, the board, your position - and I\'ll give you a real read.': 'Track mode. Log hands as you play. When you call it a night, say "done" and I\'ll confirm your buy-in and cash-out before closing.';
chatbox.innerHTML = `<div class="flex items-start"><div class="bg-[#1a1a1a] text-gray-200 px-4 py-2.5 rounded-2xl rounded-tl-sm text-sm max-w-[85%] shadow-sm">${intro}</div></div>`;
document.getElementById('user-input').placeholder = currentMode === 'coach'? 'Type your hand...': 'Log your hand...';
renderQuickChips();
refreshSessionBanner();
}
function renderQuickChips() {
const chips = document.getElementById('quick-chips');
if (currentMode !== 'track' || recapActive) { chips.classList.add('hidden'); chips.innerHTML = ''; return; }
const mk = (amt) => currentUnits === 'dollars' ? '$' + amt.toFixed(2) : (currentUnits === 'bb' ? amt.toFixed(2) + 'bb' : amt + ' chips');
const defs = [
{ a: 'Won +' + mk(20), b: 'Won ' + mk(20) },
{ a: 'Rebuy ' + mk(5), b: 'Bought in ' + mk(5) },
{ a: 'Rebuy ' + mk(20), b: 'Bought in ' + mk(20) },
{ a: 'Rebuy ' + mk(100), b: 'Bought in ' + mk(100) },
{ a: 'Done', b: 'Done for the night' }
];
chips.innerHTML = defs.map(c => `<button type="button" data-fill="${c.b}" class="flex-shrink-0 bg-[#1a1a1a] hover:bg-neutral-800 border border-neutral-800 text-gray-300 text-xs font-medium px-3 py-1.5 rounded-full transition">${c.a}</button>`).join('');
if (recapSessionId && !recapActive) {
chips.innerHTML += `<button type="button" data-action="recap" class="flex-shrink-0 border border-emerald-600 text-emerald-400 hover:bg-emerald-600 hover:text-white text-xs font-semibold px-3 py-1.5 rounded-full transition">Recap session</button>`;
}
chips.classList.remove('hidden');
}
async function offerRecap() {
if (recapActive) return;
const sessions = await fetchSessions();
const closed = sessions.find(s => s.status === 'closed');
if (!closed) { recapSessionId = null; return; }
recapSessionId = closed.id;
renderQuickChips();
appendRecapPrompt();
}
function appendRecapPrompt() {
const chatbox = document.getElementById('chatbox');
const old = document.getElementById('recap-prompt');
if (old) old.remove();
if (!chatbox || !recapSessionId) return;
const w = document.createElement('div');
w.id = 'recap-prompt';
w.className = 'flex flex-col items-start';
w.innerHTML = `<div class="bg-purple-900/40 border border-purple-800 text-gray-100 px-4 py-3 rounded-2xl rounded-tl-sm text-sm max-w-[85%] shadow-sm space-y-2">
<p>Night's over. Want a coaching review of how you played?</p>
<button onclick="startRecap()" class="bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition">Recap with coach</button>
</div>`;
chatbox.appendChild(w);
chatbox.scrollTop = chatbox.scrollHeight;
}
async function startRecap() {
if (!recapSessionId || recapActive) return;
recapActive = true;
const chatbox = document.getElementById('chatbox');
chatbox.innerHTML = `<div class="flex items-start"><div class="bg-purple-900/40 text-gray-100 px-4 py-2.5 rounded-2xl rounded-tl-sm text-sm max-w-[85%] shadow-sm">Recap mode - I'll go over your finished session, hand by hand. This conversation doesn't touch your logged hands or stats.</div></div>`;
const banner = document.getElementById('session-banner');
banner.innerHTML = `<div class="bg-purple-900/30 border border-purple-800 rounded-xl px-3 py-2 flex items-center gap-2">
<span class="text-xs font-semibold text-purple-400">Recap session</span>
<span class="ml-auto text-xs text-gray-500">won't affect your stats</span>
</div>`;
banner.classList.remove('hidden');
document.getElementById('quick-chips').classList.add('hidden');
const inp = document.getElementById('user-input');
inp.placeholder = 'Ask about the session...';
inp.value = 'Review my session. Where did I play well, and where did I lose value?';
document.getElementById('chat-form').requestSubmit();
}
document.getElementById('quick-chips').addEventListener('click', (e) => {
const btn = e.target.closest('button[data-fill], button[data-action]');
if (!btn) return;
if (btn.dataset.action === 'recap') { startRecap(); return; }
const inp = document.getElementById('user-input');
inp.value = btn.dataset.fill;
inp.focus();
chatbox.scrollTop = chatbox.scrollHeight;
});
async function refreshSessionBanner() {
const banner = document.getElementById('session-banner');
if (!banner || recapActive) return;
if (currentMode !== 'track') { banner.classList.add('hidden'); return; }
const sessions = await fetchSessions();
const open = sessions.find(s => s.status === 'open');
if (open) {
const bin = open.buyins || 0;
banner.innerHTML = `<div class="bg-emerald-900/30 border border-emerald-800 rounded-xl px-3 py-2 flex items-center gap-2">
<div class="w-2 h-2 bg-emerald-500 rounded-full pulse-green"></div>
<span class="text-xs font-semibold text-emerald-400">Session open</span>
<span class="ml-auto text-xs text-emerald-400">${bin > 0 ? '$' + bin.toFixed(2) + ' in' : 'no buy-ins yet'}</span>
</div>`;
} else {
banner.innerHTML = `<div class="bg-neutral-900/60 border border-neutral-800 rounded-xl px-3 py-2 flex items-center gap-2">
<span class="text-xs text-gray-500">No open session.</span>
<button onclick="startSession()" id="start-session-btn" class="ml-auto bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition">Start session</button>
</div>`;
}
banner.classList.remove('hidden');
}
let sessionStarting = false;
async function startSession() {
if (sessionStarting) return;
const data = await authedFetch('/api/sessions');
const hasOpen = data && (data.sessions || []).some(s => s.status === 'open');
if (hasOpen) { refreshSessionBanner(); return; }
const unitWord = currentUnits === 'bb' ? 'bb' : currentUnits === 'chips' ? 'chips' : '$';
const amtStr = prompt('Buy-in amount (' + unitWord + ') - or leave blank to start without one:', currentDefaultBuyin || '5');
if (amtStr === null) return;
let amount = 0;
if (amtStr.trim() !== '') {
amount = parseFloat(amtStr);
if (isNaN(amount) || amount < 0) { alert('Enter a valid buy-in amount (' + (currentUnits === 'bb' ? 'bb' : currentUnits === 'chips' ? 'chips' : '$') + ').'); return; }
}
sessionStarting = true;
try {
const res = await authedFetch('/api/session/start', { method: 'POST', body: JSON.stringify({ amount: amount, units: currentUnits }) });
if (res && res.error) { alert(res.error); return; }
checkSession();
refreshSessionBanner();
} finally { sessionStarting = false; }
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
tabChat.addEventListener('click', () => { setActiveTab(tabChat); chatView.classList.remove('hidden'); renderQuickChips(); refreshSessionBanner(); });
tabHistory.addEventListener('click', () => { setActiveTab(tabHistory); historyView.classList.remove('hidden'); loadHistory(); });
tabStats.addEventListener('click', () => { setActiveTab(tabStats); statsView.classList.remove('hidden'); loadStats(); });
tabSocial.addEventListener('click', () => { setActiveTab(tabSocial); socialView.classList.remove('hidden'); loadSocial(); });
function goToTab(which) {
if (which === 'chat' && currentMode !== 'track') modeTrackBtn.click();
const map = { home: tabHome, chat: tabChat, history: tabHistory, stats: tabStats, social: tabSocial };
const btn = map[which];
if (btn) btn.click();
}
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
el.innerHTML = `<div class="text-center py-12 space-y-4">
<div class="mx-auto w-16 h-16 rounded-2xl bg-[#1a1a1a] flex items-center justify-center">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-8 h-8 text-emerald-500"><path fill-rule="evenodd" d="M12 2.25c-5.385 0-9.75 4.365-9.75 9.75s4.365 9.75 9.75 9.75 9.75-4.365 9.75-9.75S17.385 2.25 12 2.25zM8.25 10.5a.75.75 0 00-.75.75v2.25a.75.75 0 001.5 0v-2.25a.75.75 0 00-.75-.75zm3.75 0a.75.75 0 00-.75.75v3.75a.75.75 0 001.5 0V11.25a.75.75 0 00-.75-.75zm3.75 0a.75.75 0 00-.75.75v1.5a.75.75 0 001.5 0v-1.5a.75.75 0 00-.75-.75z" clip-rule="evenodd"/></svg>
</div>
<p class="text-lg font-semibold">No data yet.</p>
<p class="text-sm text-gray-500">Log your first hand in Track mode to start building stats, buy-in history, and profit trends.</p>
<div class="flex justify-center">
<button onclick="goToTab('chat')" class="bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-semibold px-5 py-2.5 rounded-lg transition shadow-md shadow-emerald-900/40">Start tracking</button>
</div>
</div>`;
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

let bankroll = null;
try { bankroll = await authedFetch('/api/bankroll'); } catch {}

if (open) {
const bin = open.buyins || 0;
html += `<div class="bg-emerald-900/30 border border-emerald-800 rounded-xl p-4 space-y-1">
<div class="flex items-center gap-2">
<div class="w-2 h-2 bg-emerald-500 rounded-full pulse-green"></div>
<span class="text-xs font-semibold text-emerald-400">Session open</span>
${bin > 0 ? `<span class="ml-auto text-xs text-emerald-400">${bin.toFixed(2)} in</span>` : ''}
</div>
<p class="text-xs text-gray-500">Log hands. Say "done" when you're ready and confirm your buy-in and cash-out to close.</p>
</div>`;
}

if (bankroll && typeof bankroll.amount === 'number') {
const amt = bankroll.amount || 0;
const goal = bankroll.goal;
const pct = goal > 0 ? Math.min(100, Math.round((amt / goal) * 100)) : 0;
html += `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-2">
<div class="flex items-center justify-between">
<h3 class="text-sm font-semibold text-gray-300">Bankroll</h3>
<button onclick="openBankroll()" class="text-xs text-gray-500 hover:text-emerald-400 transition">${bankroll.goal ? 'edit' : (amt === 0 ? 'setup' : 'set goal')}</button>
</div>
<div class="flex items-end justify-between">
<p class="text-2xl font-bold ${amt >= 0 ? 'text-emerald-400' : 'text-red-400'}">$${amt.toFixed(2)}</p>
${goal ? `<p class="text-xs text-gray-500">Goal $${goal.toFixed(2)}</p>` : ''}
</div>
${goal && goal > 0 ? `<div class="w-full bg-black rounded-full h-2"><div class="bar bg-emerald-500" style="width: ${pct}%"></div></div><p class="text-xs text-gray-500">${pct}% of goal</p>` : ''}
<p class="text-[10px] text-gray-600">Auto-updates with your session profit.</p>
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
const label = s.label ? s.label + ' · ' : '';
return `<button onclick="openSession(${s.id}, 'home-view')" class="w-full flex justify-between items-center text-xs text-left hover:bg-black/40 rounded-lg px-2 py-1 -mx-2 transition">
<span class="text-gray-400">${label}${d}</span>
<span class="font-semibold ${p >= 0? 'text-emerald-400': 'text-red-400'}">${p >= 0? '+': ''}$${p.toFixed(2)}</span>
</button>`;
}).join('')}
</div>`;
}

el.innerHTML = html;
}
async function loadHistory() {
const entries = await fetchHistory();
const el = document.getElementById('history-view');
if (entries.length === 0) {
el.innerHTML = `<div class="text-center py-16 space-y-4">
<div class="mx-auto w-16 h-16 rounded-2xl bg-[#1a1a1a] flex items-center justify-center">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-8 h-8 text-gray-500"><path d="M4.848 2.771A49.144 49.144 0 0112 2.25c2.43 0 4.817.178 7.152.52 1.978.292 3.348 2.024 3.348 3.97v6.02c0 1.946-1.37 3.678-3.348 3.97a48.901 48.901 0 01-3.476.383.39.39 0 00-.297.17l-2.755 4.133a.75.75 0 01-1.248 0l-2.755-4.133a.39.39 0 00-.297-.17 48.9 48.9 0 01-3.476-.384c-1.978-.29-3.348-2.024-3.348-3.97V6.741c0-1.946 1.37-3.678 3.348-3.97z"/></svg>
</div>
<p class="text-sm text-gray-400">No hands yet.</p>
<div class="flex justify-center">
<button onclick="goToTab('chat')" class="bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-semibold px-5 py-2.5 rounded-lg transition shadow-md shadow-emerald-900/40">Log a hand</button>
</div>
</div>`;
return;
}
el.innerHTML = `<div class="space-y-3">
<div class="flex gap-2">
<input id="hist-search" type="text" placeholder="Search hands..." value="" oninput="applyHandFilters()" class="flex-1 bg-black text-gray-200 text-sm rounded-lg px-3 py-2.5 border border-neutral-800 outline-none focus:ring-2 focus:ring-emerald-500 placeholder-gray-600" />
<select id="hist-result" onchange="applyHandFilters()" class="bg-black text-gray-300 text-xs rounded-lg px-2 py-2.5 border border-neutral-800 outline-none focus:ring-2 focus:ring-emerald-500">
<option value="">All</option>
<option value="won">Won</option>
<option value="lost">Lost</option>
</select>
<select id="hist-tier" onchange="applyHandFilters()" class="bg-black text-gray-300 text-xs rounded-lg px-2 py-2.5 border border-neutral-800 outline-none focus:ring-2 focus:ring-emerald-500">
<option value="">Any tier</option>
<option value="premium">Premium</option>
<option value="strong">Strong</option>
<option value="playable">Playable</option>
<option value="speculative">Speculative</option>
<option value="trash">Trash</option>
</select>
</div>
<div id="hist-list" class="space-y-3"></div>
</div>`;
renderHandList();
}
function isWon(r) { return ['won','win','w'].includes((r||'').toLowerCase()); }
function applyHandFilters() { renderHandList(); }
function renderHandList() {
const listEl = document.getElementById('hist-list');
if (!listEl) return;
const allEntries = cachedHistory || [];
const q = (document.getElementById('hist-search').value || '').toLowerCase().trim();
const rf = document.getElementById('hist-result').value;
const tf = document.getElementById('hist-tier').value;
const entries = allEntries.filter(e => {
if (rf && !(isWon(e.result) === (rf === 'won'))) return false;
if (tf && e.tier && e.tier.toLowerCase() !== tf) return false;
if (tf && !e.tier) return false;
if (q) {
const hay = ((e.hand || '') + ' ' + (e.position || '') + ' ' + (e.player_action || '') + ' ' + (e.reply || '')).toLowerCase();
if (!hay.includes(q)) return false;
}
return true;
});
if (entries.length === 0) { listEl.innerHTML = '<p class="text-sm text-gray-500 text-center py-8">No matching hands.</p>'; return; }
listEl.innerHTML = entries.map(e => {
let top = '<div class="flex items-center gap-2 flex-wrap">';
if (e.hand) top += `<span class="text-sm font-bold text-emerald-400">${e.hand}</span>`;
if (e.tier) top += `<span class="text-xs font-semibold px-2 py-0.5 rounded ${tierClass(e.tier)} text-white capitalize">${e.tier}</span>`;
if (e.position) top += `<span class="text-xs text-gray-500">${e.position}</span>`;
if (e.player_action) top += `<span class="text-xs font-semibold text-gray-300">${e.player_action}</span>`;
top += `<span class="text-xs text-gray-600 ml-auto">${new Date(e.created_at).toLocaleDateString()}</span>`;
top += `<button onclick="beginEdit('${e.id}')" class="text-[10px] text-gray-600 hover:text-emerald-400 ml-1 transition">edit</button>`;
top += '</div>';
let resultHTML = '';
if (e.result) {
resultHTML = `<div class="flex items-center gap-2 pt-1 border-t border-neutral-800 mt-1">
<span class="text-xs font-semibold ${isWon(e.result)? 'text-emerald-400': 'text-red-400'}">${isWon(e.result)? 'Won': 'Lost'}</span>
${e.amount? `<span class="text-xs ${isWon(e.result)? 'text-emerald-400': 'text-red-400'}">${unitAmount(e.amount)}</span>`: ''}
</div>`;
}
return `<div id="hist-${e.id}" class="bg-[#1a1a1a] rounded-xl p-4 space-y-2">${top}<p class="text-sm text-gray-300">${e.reply}</p>${resultHTML}</div>`;
}).join('');
}
function beginEdit(id) {
const e = (cachedHistory || []).find(h => h.id == id);
if (!e) return;
const card = document.getElementById('hist-' + id);
card.innerHTML = `<div class="space-y-2">
<div class="flex gap-2">
<input id="eh-${id}" value="${e.hand || ''}" placeholder="Hand" class="flex-1 bg-black text-emerald-400 text-sm font-bold rounded px-2 py-1.5 border border-neutral-800 outline-none focus:ring-2 focus:ring-emerald-500" />
<input id="ep-${id}" value="${e.position || ''}" placeholder="Position" class="w-20 bg-black text-gray-300 text-xs rounded px-2 py-1.5 border border-neutral-800 outline-none focus:ring-2 focus:ring-emerald-500" />
</div>
<div class="flex gap-2">
<input id="ea-${id}" value="${e.player_action || ''}" placeholder="Action" class="flex-1 bg-black text-gray-300 text-xs rounded px-2 py-1.5 border border-neutral-800 outline-none focus:ring-2 focus:ring-emerald-500" />
<select id="er-${id}" class="bg-black text-gray-300 text-xs rounded px-2 py-1.5 border border-neutral-800 outline-none"><option value="">—</option><option value="won" ${isWon(e.result)? 'selected': ''}>Won</option><option value="lost" ${e.result && !isWon(e.result) ? 'selected': ''}>Lost</option></select>
<input id="eamt-${id}" type="number" value="${e.amount || ''}" placeholder="$" class="w-16 bg-black text-gray-300 text-xs rounded px-2 py-1.5 border border-neutral-800 outline-none focus:ring-2 focus:ring-emerald-500" />
</div>
<div class="flex items-center gap-2 pt-1">
<button onclick="saveEdit('${id}')" class="bg-emerald-600 hover:bg-emerald-500 text-white text-[11px] font-semibold px-3 py-1 rounded transition">Save</button>
<button onclick="cancelEdit()" class="text-gray-500 hover:text-gray-300 text-[11px] px-2 py-1 transition">Cancel</button>
<button onclick="deleteHand('${id}')" class="text-red-500 hover:text-red-400 text-[11px] ml-auto">Delete</button>
</div></div>`;
}
async function saveEdit(id) {
const hand = document.getElementById('eh-' + id).value.trim();
const position = document.getElementById('ep-' + id).value.trim();
const action = document.getElementById('ea-' + id).value.trim();
const result = document.getElementById('er-' + id).value || null;
const amtVal = document.getElementById('eamt-' + id).value;
const amount = amtVal ? parseFloat(amtVal) : null;
await authedFetch('/api/history/update', { method: 'POST', body: JSON.stringify({ id, hand, position, player_action: action, result, amount }) });
cachedHistory = null;
loadHistory();
}
function cancelEdit() { cachedHistory = null; loadHistory(); }
async function deleteHand(id) {
if (!confirm('Delete this hand entry?')) return;
await authedFetch('/api/history/delete', { method: 'POST', body: JSON.stringify({ id }) });
cachedHistory = null;
loadHistory();
}

async function loadStats() {
const entries = await fetchHistory();
const sessions = await fetchSessions();
const el = document.getElementById('stats-view');
if (entries.length === 0 && sessions.length === 0) {
el.innerHTML = `<div class="text-center py-16 space-y-4">
<div class="mx-auto w-16 h-16 rounded-2xl bg-[#1a1a1a] flex items-center justify-center">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-8 h-8 text-gray-500"><path d="M18.375 2.25c-1.035 0-1.875.84-1.875 1.875v15.75c0 1.035.84 1.875 1.875 1.875h.75c1.035 0 1.875-.84 1.875-1.875V4.125c0-1.036-.84-1.875-1.875-1.875h-.75zM9.75 8.625c0-1.036.84-1.875 1.875-1.875h.75c1.036 0 1.875.84 1.875 1.875v11.25c0 1.035-.84 1.875-1.875 1.875h-.75a1.875 1.875 0 01-1.875-1.875V8.625zM3 13.125c0-1.036.84-1.875 1.875-1.875h.75c1.036 0 1.875.84 1.875 1.875v6.75c0 1.035-.84 1.875-1.875 1.875h-.75A1.875 1.875 0 013 19.875v-6.75z"/></svg>
</div>
<p class="text-sm text-gray-400">No stats yet.</p>
<div class="flex justify-center">
<button onclick="goToTab('chat')" class="bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-semibold px-5 py-2.5 rounded-lg transition shadow-md shadow-emerald-900/40">Start tracking</button>
</div>
</div>`;
return;
}

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
const totalBuyins = closed.reduce((sum, s) => sum + (s.buyins || 0), 0);
const totalCashouts = closed.reduce((sum, s) => sum + (s.cashout || 0), 0);
const roi = totalBuyins > 0 ? (totalProfit / totalBuyins) * 100 : null;
const roiStr = roi === null ? '-' : (roi >= 0 ? '+' : '') + roi.toFixed(1) + '%';

let html = '';
if (open) {
const bin = open.buyins || 0;
html += `<div class="bg-emerald-900/30 border border-emerald-800 rounded-xl p-4 space-y-1">
<div class="flex items-center gap-2">
<div class="w-2 h-2 bg-emerald-500 rounded-full pulse-green"></div>
<span class="text-xs font-semibold text-emerald-400">Session open</span>
${bin > 0 ? `<span class="ml-auto text-xs text-emerald-400">${bin.toFixed(2)} in</span>` : ''}
</div>
<p class="text-xs text-gray-500">Log hands. Say "done" when you're ready and confirm your buy-in and cash-out to close.</p>
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
</div>${totalBuyins > 0 ? `<div class="grid grid-cols-2 gap-3">
<div class="bg-black rounded-lg p-3 text-center"><p class="text-xl font-bold text-gray-300">$${totalBuyins.toFixed(2)}</p><p class="text-xs text-gray-500">Total buy-ins</p></div>
<div class="bg-black rounded-lg p-3 text-center"><p class="text-xl font-bold text-gray-300">$${totalCashouts.toFixed(2)}</p><p class="text-xs text-gray-500">Total cashouts</p></div>
<div class="bg-black rounded-lg p-3 text-center"><p class="text-xl font-bold ${roi >= 0? 'text-emerald-400': 'text-red-400'}">${roiStr}</p><p class="text-xs text-gray-500">ROI</p></div>
<div class="bg-black rounded-lg p-3 text-center"><p class="text-xl font-bold text-gray-300">$${(totalBuyins / closed.length).toFixed(2)}</p><p class="text-xs text-gray-500">Avg buy-in</p></div>
</div>` : ''}
</div>`;
const recent = closed.slice(0, 5).reverse();
html += `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-3">
<h3 class="text-sm font-semibold text-gray-300">Recent nights</h3>
${recent.map(s => {
const d = new Date(s.closed_at || s.created_at).toLocaleDateString();
const p = s.profit || 0;
const label = s.label ? s.label + ' · ' : '';
const nit = s.buyins ? `<span class="text-gray-500">$${(s.buyins)} in</span> ` : '';
return `<button onclick="openSession(${s.id}, 'stats-view')" class="w-full flex justify-between items-center text-xs text-left hover:bg-black/40 rounded-lg px-2 py-1 -mx-2 transition">
<span class="text-gray-400">${label}${d}</span>
<div class="flex items-center gap-2">${nit}<span class="font-semibold ${p >= 0? 'text-emerald-400': 'text-red-400'}">${p >= 0? '+': ''}$${p.toFixed(2)}</span></div>
</button>`;
}).join('')}
</div>`;
if (closed.length >= 2) {
const chartSessions = closed.slice(-10);
const maxAbs = Math.max(1, ...chartSessions.map(s => Math.abs(s.profit || 0)));
html += `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-3">
<h3 class="text-sm font-semibold text-gray-300">Profit trend</h3>
<div class="flex items-end gap-1 h-20">
${chartSessions.map(s => {
const p = s.profit || 0;
const pct = Math.max(4, Math.round((Math.abs(p) / maxAbs) * 100));
const color = p >= 0 ? 'bg-emerald-500' : 'bg-red-500';
const d = new Date(s.closed_at || s.created_at).toLocaleDateString([], {month:'short', day:'numeric'});
return `<div class="flex-1 flex flex-col items-center gap-0.5 h-full justify-end" title="${d}: ${p >= 0 ? '+' : ''}$${p.toFixed(2)}"><div class="w-full ${color} rounded-sm" style="height:${pct}%"></div></div>`;
}).join('')}
</div>
</div>`;
} else {
html += `<div class="bg-[#1a1a1a] rounded-xl p-4"><p class="text-sm text-gray-500 text-center">Track a session and close it to see your nights.</p></div>`;
}
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
const mode = recapActive ? 'recap' : currentMode;
const body = { message: text, mode, units: currentUnits };
if (recapActive && recapSessionId) body.session_id = recapSessionId;
try {
const h = {'Content-Type': 'application/json'}; if (session) h['Authorization'] = 'Bearer ' + session.access_token;
const res = await fetch('/api/chat', { method: 'POST', headers: h, body: JSON.stringify(body) });
const data = await res.json();
lb.textContent = data.reply || data.error || 'No response.';
if (!recapActive) cachedHistory = null;
if (data.reply && data.reply.includes('Session closed') && !recapActive) {
checkSession();
offerRecap();
}
if (recapActive && data.recap_session_id) recapSessionId = data.recap_session_id;
refreshSessionBanner();
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
if (stats.total_buyins) {
html += `<div class="grid grid-cols-2 gap-2">`;
const roi = stats.roi === null || stats.roi === undefined ? '-' : stats.roi + '%';
html += `<div class="bg-black rounded-lg p-3 text-center"><p class="text-xl font-bold text-gray-300">${money(stats.total_buyins)}</p><p class="text-xs text-gray-500">Buy-ins</p></div>`;
html += `<div class="bg-black rounded-lg p-3 text-center"><p class="text-xl font-bold text-gray-300">${money(stats.total_cashouts)}</p><p class="text-xs text-gray-500">Cashouts</p></div>`;
html += `<div class="bg-black rounded-lg p-3 text-center"><p class="text-xl font-bold ${stats.roi >= 0 ? 'text-emerald-400' : 'text-red-400'}">${roi}</p><p class="text-xs text-gray-500">ROI</p></div>`;
html += `<div class="bg-black rounded-lg p-3 text-center"><p class="text-xl font-bold text-gray-300">${money(stats.total_buyins / stats.nights)}</p><p class="text-xs text-gray-500">Avg buy-in</p></div>`;
html += '</div>';
}
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
html += `<div id="discord-card" class="bg-[#1a1a1a] rounded-xl p-4 space-y-2">
<h3 class="text-sm font-semibold text-gray-300">Discord</h3>
<p class="text-xs text-gray-500">Post your nights to the community server and tag yourself.</p>
<div id="discord-status" class="text-xs text-gray-400">Loading...</div>
</div>`;
html += `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-3">
<h3 class="text-sm font-semibold text-gray-300">Discord server</h3>
<p class="text-xs text-gray-500">Join the table, ask about hands, and share your nights.</p>
<div id="discord-server-status" class="space-y-2">
<p class="text-xs text-gray-400">Loading...</p>
</div>
</div>`;
el.innerHTML = html;
loadLeaderboard();
loadDiscordStatus();
loadDiscordServer();
}
async function loadDiscordServer() {
const el = document.getElementById('discord-server-status');
if (!el) return;
const data = await authedFetch('/api/discord/widget');
const link = await authedFetch('/api/discord/link');
if (!data) { el.innerHTML = '<p class="text-xs text-gray-500">Could not load the server widget.</p>'; return; }
let html = '';
const invite = data.invite || 'https://discord.gg/KB4rNwnea';
if (data.ok) {
html += `<p class="text-xs text-emerald-400"><span class="inline-block w-2 h-2 bg-emerald-500 rounded-full mr-1.5 pulse-green"></span>${data.presence_count} online now</p>`;
}
if (link && link.linked) {
html += `<button onclick="shareTonight()" class="bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold px-4 py-2 rounded-lg transition">Share my latest night</button>`;
}
html += `<a href="${invite}" target="_blank" rel="noopener" class="inline-block bg-[#5865F2] hover:bg-[#4752C4] text-white text-xs font-semibold px-4 py-2 rounded-lg transition">Join Discord</a>`;
if (!data.ok) html += '<p class="text-[10px] text-gray-600">Live presence hidden - widget not enabled in server settings.</p>';
el.innerHTML = html;
}
async function loadDiscordStatus() {
const statusEl = document.getElementById('discord-status');
if (!statusEl) return;
const config = await authedFetch('/api/discord/config');
const link = await authedFetch('/api/discord/link');
if (!config || !config.enabled) { statusEl.innerHTML = '<p class="text-gray-500">Discord sharing isn\'t configured by the owner yet.</p>'; return; }
if (!link || !link.linked) {
statusEl.innerHTML = `<button onclick="startDiscordLink()" class="bg-[#5865F2] hover:bg-[#4752C4] text-white text-xs font-semibold px-4 py-2 rounded-lg transition">Connect Discord</button>`;
} else {
statusEl.innerHTML = `<p class="text-gray-400">Connected as <span class="text-[#5865F2] font-semibold">@${link.username}</span></p>`;
}
}
async function startDiscordLink() {
const config = await authedFetch('/api/discord/config');
if (!config || !config.client_id) { alert('Discord sharing isn\'t configured yet.'); return; }
const state = Math.random().toString(36).slice(2);
localStorage.setItem('discord_state', state);
const redirect = encodeURIComponent(window.location.origin + '/');
window.location.href = 'https://discord.com/api/oauth2/authorize?client_id=' + config.client_id + '&response_type=code&redirect_uri=' + redirect + '&scope=identify&state=' + state;
}
async function shareTonight() {
const data = await authedFetch('/api/discord/share', { method: 'POST', body: JSON.stringify({ tz: new Date().getTimezoneOffset() }) });
if (data && data.error) { alert(data.error); return; }
const s = document.getElementById('discord-status');
if (s) s.innerHTML = '<p class="text-emerald-400">Posted! Check your Discord channel.</p>';
setTimeout(() => { loadDiscordStatus(); loadDiscordServer(); }, 3000);
}
async function handleDiscordCallback() {
const params = new URLSearchParams(window.location.search);
const code = params.get('code');
const state = params.get('state');
if (!code || !state) return false;
if (state !== localStorage.getItem('discord_state')) { history.replaceState(null, '', window.location.pathname); return false; }
localStorage.removeItem('discord_state');
const { data: { session } } = await sb.auth.getSession();
if (!session) { history.replaceState(null, '', window.location.pathname); alert('Sign in first, then connect Discord.'); return true; }
const data = await authedFetch('/api/discord/link', { method: 'POST', body: JSON.stringify({ code, redirect_uri: window.location.origin + '/' }) });
history.replaceState(null, '', window.location.pathname);
if (data && data.ok) alert('Connected to Discord as @' + data.username);
else alert((data && data.error) || 'Could not connect Discord.');
return true;
}
async function openSession(sid, targetId) {
const el = document.getElementById(targetId);
el.innerHTML = '<p class="text-sm text-gray-500 text-center py-8">Loading...</p>';
const data = await authedFetch('/api/session?id=' + sid);
if (!data || data.error) { el.innerHTML = '<p class="text-sm text-red-400 text-center py-8">' + ((data && data.error) || 'Not found.') + '</p>'; return; }
const s = data.session;
const d = new Date(s.closed_at || s.created_at);
const dateStr = d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
const p = s.profit || 0;
const pStr = p >= 0 ? '+$' + p.toFixed(2) : '-$' + Math.abs(p).toFixed(2);
let html = `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-2">
<button onclick="relaunchTab('${targetId}')" class="text-xs text-gray-400 hover:text-emerald-400">&larr; Back</button>
<div class="flex items-center justify-between pt-1">
<h2 class="text-base font-bold text-gray-200">${s.label || 'Session'}</h2>
<span class="text-xs text-gray-500">${dateStr}</span>
</div>
<div class="grid grid-cols-3 gap-2 mt-2">
<div class="bg-black rounded-lg p-2 text-center"><p class="text-sm font-bold ${p >= 0? 'text-emerald-400': 'text-red-400'}">${pStr}</p><p class="text-[10px] text-gray-500">Profit</p></div>
<div class="bg-black rounded-lg p-2 text-center"><p class="text-sm font-bold text-gray-300">$${(s.buyins_total || 0).toFixed(2)}</p><p class="text-[10px] text-gray-500">Buy-ins</p></div>
<div class="bg-black rounded-lg p-2 text-center"><p class="text-sm font-bold text-gray-300">${s.hands.length}</p><p class="text-[10px] text-gray-500">Hands</p></div>
</div>
<div class="flex gap-3 pt-1">
<button onclick="renameSession(${s.id})" class="text-xs text-gray-500 hover:text-emerald-400 transition">Rename</button>
<button onclick="deleteSession(${s.id})" class="text-xs text-gray-500 hover:text-red-400 transition">Delete</button>
<button onclick="recapSession(${s.id})" class="text-xs text-emerald-400 hover:text-emerald-300 ml-auto transition">Recap with coach</button>
</div>
</div>`;
if (s.buyin_list && s.buyin_list.length > 0) {
html += `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-2">
<h3 class="text-sm font-semibold text-gray-300">Buy-ins</h3>
${s.buyin_list.map(b => `<div class="flex justify-between text-xs"><span class="text-gray-400">${new Date(b.created_at).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}</span><span class="text-gray-300">$${b.amount.toFixed(2)}</span></div>`).join('')}
</div>`;
}
if (s.hands.length > 0) {
html += `<div class="bg-[#1a1a1a] rounded-xl p-4 space-y-2">
<h3 class="text-sm font-semibold text-gray-300">Hands</h3>
${s.hands.map(h => {
let left = h.hand || '?';
if (h.position) left += ' / ' + h.position;
if (h.player_action) left += ' / ' + h.player_action;
let right = '';
if (h.result) { const w = isWon(h.result); right += `<span class="${w ? 'text-emerald-400' : 'text-red-400'}">${w ? 'Won' : 'Lost'}</span>`; }
if (h.amount) right += ` <span class="text-gray-400">${unitAmount(h.amount)}</span>`;
return `<div class="flex justify-between text-xs py-1 border-b border-neutral-800 last:border-0"><span class="text-emerald-400 font-semibold">${left}</span><span>${right}</span></div>`;
}).join('')}
</div>`;
}
el.innerHTML = html;
}
function relaunchTab(targetId) {
if (targetId === 'home-view') goToTab('home');
else goToTab('stats');
}
function renameSession(sid) {
const name = prompt('Session name (e.g. "Tuesday night game"):', '');
if (name === null) return;
authedFetch('/api/session/rename', { method: 'POST', body: JSON.stringify({ id: sid, label: name.trim() }) }).then(() => {
cachedHistory = null;
openSession(sid, document.querySelector('#home-view:not(.hidden), #stats-view:not(.hidden)') ? document.querySelector('#home-view:not(.hidden), #stats-view:not(.hidden)').id : 'stats-view');
});
}
function deleteSession(sid) {
if (!confirm('Delete this session and all its hands? This cannot be undone.')) return;
authedFetch('/api/session/delete', { method: 'POST', body: JSON.stringify({ id: sid }) }).then(() => {
cachedHistory = null;
const active = document.querySelector('#home-view:not(.hidden), #stats-view:not(.hidden)');
if (active && active.id === 'home-view') goToTab('home');
else goToTab('stats');
});
}
function recapSession(sid) {
recapSessionId = sid;
recapActive = false;
goToTab('chat');
setTimeout(() => startRecap(), 150);
}
async function openBankroll() {
const data = await authedFetch('/api/bankroll');
const amtStr = prompt('Current bankroll amount ($):', data && typeof data.amount === 'number' ? String(data.amount) : '');
if (amtStr === null) return;
const val = parseFloat(amtStr);
if (isNaN(val)) { alert('Enter a number for bankroll.'); return; }
const goalStr = prompt('Goal amount ($) - leave blank for no goal:', data && data.goal ? String(data.goal) : '');
if (goalStr === null) return;
let goal = null;
if (goalStr.trim() !== '') { const g = parseFloat(goalStr); if (isNaN(g)) { alert('Enter a number for the goal.'); return; } goal = g; }
await authedFetch('/api/bankroll', { method: 'POST', body: JSON.stringify({ amount: val, goal: goal }) });
loadHome();
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