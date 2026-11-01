/* SkillBuddy voice + personality layer. Speech is opt-in and handled locally by the browser. */
(() => {
  const $ = (s) => document.querySelector(s);
  const widget = $('#assistantWidget');
  const messages = $('#assistantMessages');
  const voiceToggle = $('#petVoiceEnabled');
  const personalitySelect = $('#petPersonality');
  const status = $('#petVoiceStatus');
  const testButton = $('#petVoiceTest');
  const stopButton = $('#petVoiceStop');
  const listenButton = $('#petListenButton');
  const inlineMic = $('#assistantMicInline');
  const input = $('#assistantInput');
  if (!widget || !messages || !voiceToggle || !personalitySelect) return;

  const key = 'skillswap_pet_personality_';
  const profiles = {
    cheerful: { pitch: 1.16, rate: 1.04, intro: 'Yay, let us make progress!', mood: 'excited', voiceHints: ['female','samantha'] },
    calm: { pitch: 0.94, rate: 0.91, intro: 'Take your time. I am right here.', mood: 'curious', voiceHints: ['female','aria'] },
    playful: { pitch: 1.28, rate: 1.09, intro: 'Hehe, curious minds activate!', mood: 'curious', voiceHints: ['female','zira'] },
    coach: { pitch: 0.99, rate: 0.98, intro: 'One clear step at a time. You have got this.', mood: 'proud', voiceHints: ['male','david'] }
  };
  const read = (name, fallback) => { try { return localStorage.getItem(key + name) ?? fallback; } catch (_) { return fallback; } };
  const write = (name, value) => { try { localStorage.setItem(key + name, value); } catch (_) {} };
  let enabled = read('enabled', 'off') === 'on';
  let personality = profiles[read('style', 'cheerful')] ? read('style', 'cheerful') : 'cheerful';
  let recognition = null;
  let listening = false;
  let voices = [];
  let lastSpoken = '';

  const setStatus = (message) => { if (status) status.textContent = message; };
  const getSpeech = () => window.speechSynthesis;
  function loadVoices() { voices = getSpeech()?.getVoices?.() || []; }
  loadVoices();
  if (getSpeech()) getSpeech().addEventListener?.('voiceschanged', loadVoices);

  function preferredVoice() {
    const p = profiles[personality];
    const english = voices.filter(v => /^en(-|_)/i.test(v.lang));
    for (const hint of p.voiceHints) {
      const found = english.find(v => v.name.toLowerCase().includes(hint));
      if (found) return found;
    }
    return english.find(v => /en-in/i.test(v.lang)) || english.find(v => /en-us/i.test(v.lang)) || english[0] || null;
  }
  function speak(text, force = false) {
    if (!getSpeech() || (!enabled && !force)) return;
    const clean = String(text || '').replace(/https?:\/\/\S+/g, 'link').replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, '').replace(/\s+/g, ' ').trim().slice(0, 650);
    if (!clean || clean === lastSpoken) return;
    lastSpoken = clean;
    getSpeech().cancel();
    const utterance = new SpeechSynthesisUtterance(clean);
    const p = profiles[personality];
    utterance.lang = preferredVoice()?.lang || 'en-IN';
    utterance.voice = preferredVoice();
    utterance.pitch = p.pitch;
    utterance.rate = p.rate;
    utterance.volume = 0.92;
    utterance.onstart = () => { widget.classList.add('personality-speaking'); setStatus(`${personality[0].toUpperCase()+personality.slice(1)} voice is speaking…`); };
    utterance.onend = utterance.onerror = () => { widget.classList.remove('personality-speaking'); setStatus(enabled ? 'Voice is on. New SkillBuddy replies will be spoken.' : 'Voice is off.'); };
    getSpeech().speak(utterance);
  }
  function reactTo(text) {
    const t = String(text || '').toLowerCase();
    widget.classList.remove('personality-excited','personality-curious','personality-proud','personality-concerned');
    let mood = profiles[personality].mood;
    if (/great|congrat|success|earned|complete|well done|correct|awesome|excellent|achievement/.test(t)) mood = 'personality-proud';
    else if (/sorry|stress|sad|tired|difficult|stuck|mistake|problem|error/.test(t)) mood = 'personality-concerned';
    else if (/why|how|curious|explore|discover|wonder/.test(t)) mood = 'personality-curious';
    else mood = mood === 'excited' ? 'personality-excited' : mood === 'proud' ? 'personality-proud' : 'personality-curious';
    widget.classList.add(mood);
    clearTimeout(reactTo.timer);
    reactTo.timer = setTimeout(() => widget.classList.remove(mood), 2600);
  }
  function updateSettings() {
    personality = personalitySelect.value;
    enabled = voiceToggle.checked;
    write('style', personality);
    write('enabled', enabled ? 'on' : 'off');
    const name = ({cheerful:'Cheerful',calm:'Calm',playful:'Playful',coach:'Coach'})[personality];
    const intro = $('#petGreeting');
    if (intro) intro.textContent = `${profiles[personality].intro} I am your ${name.toLowerCase()} SkillSwap buddy. 🤖`;
    setStatus(enabled ? `${name} voice is on. New replies will be spoken aloud.` : `${name} personality selected. Voice is off until you enable it.`);
    if (!enabled && getSpeech()) getSpeech().cancel();
  }
  personalitySelect.value = personality;
  voiceToggle.checked = enabled;
  personalitySelect.addEventListener('change', updateSettings);
  voiceToggle.addEventListener('change', updateSettings);

  testButton?.addEventListener('click', () => {
    const name = ({cheerful:'Cheerful',calm:'Calm',playful:'Playful',coach:'Coach'})[personality];
    if (!getSpeech()) { setStatus('Speech synthesis is not available in this browser. Try a current version of Chrome or Edge.'); return; }
    speak(`Hello! I am SkillBuddy in ${name} mode. ${profiles[personality].intro}`, true);
  });
  stopButton?.addEventListener('click', () => { getSpeech()?.cancel(); widget.classList.remove('personality-speaking'); setStatus('Speaking stopped.'); });

  function stopListening() {
    listening = false;
    listenButton?.classList.remove('listening');
    inlineMic?.classList.remove('listening');
    listenButton?.setAttribute('aria-pressed','false');
    if (listenButton) listenButton.textContent = '🎤 Talk to me';
  }
  function startListening() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) { setStatus('Voice input is not supported here. Use the text box, or try Chrome/Edge over HTTPS.'); return; }
    if (listening) { recognition?.stop(); stopListening(); return; }
    recognition = new SpeechRecognition();
    recognition.lang = preferredVoice()?.lang || 'en-IN';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.onstart = () => { listening = true; listenButton?.classList.add('listening'); inlineMic?.classList.add('listening'); listenButton?.setAttribute('aria-pressed','true'); if (listenButton) listenButton.textContent = '● Listening…'; setStatus('Listening now. Speak your question, then I will place it in the chat box.'); };
    recognition.onresult = (event) => { const transcript = event.results?.[0]?.[0]?.transcript || ''; if (input && transcript) { input.value = transcript; input.focus(); setStatus('I heard you. Check the text, then press Send.'); } };
    recognition.onerror = (event) => setStatus(event.error === 'not-allowed' ? 'Microphone permission was blocked. Allow microphone access in your browser settings.' : `Voice input stopped (${event.error || 'unavailable'}). You can type instead.`);
    recognition.onend = stopListening;
    try { recognition.start(); } catch (_) { stopListening(); setStatus('Could not start the microphone. Please try again.'); }
  }
  listenButton?.addEventListener('click', startListening);
  inlineMic?.addEventListener('click', startListening);

  // Observe only newly-added bot replies; restored chat history is never read aloud.
  const observer = new MutationObserver(records => {
    for (const record of records) for (const node of record.addedNodes) {
      if (!(node instanceof HTMLElement)) continue;
      if (node.classList?.contains('chat-message') && node.classList.contains('bot')) {
        const text = node.innerText || node.textContent || '';
        reactTo(text);
        speak(text);
      }
    }
  });
  observer.observe(messages, { childList: true });
  document.addEventListener('visibilitychange', () => { if (document.hidden) { getSpeech()?.cancel(); if (listening) recognition?.stop(); } });
  window.addEventListener('beforeunload', () => { getSpeech()?.cancel(); recognition?.stop(); });
  updateSettings();
})();
