/* SkillBuddy's personal room: account-backed cosmetics and gentle daily coins. */
(() => {
  const root = document.getElementById('petRoomPanel');
  if (!root) return;
  const $ = id => document.getElementById(id);
  const scene = $('petRoomScene'), shop = $('petRoomShop'), message = $('petRoomMessage');
  let loggedIn = false, roomState = null, busy = false;
  const api = async (url, options={}) => {
    const response = await fetch(url, {credentials:'same-origin', ...options, headers:{'Content-Type':'application/json', ...(options.headers||{})}});
    const data = await response.json().catch(()=>({}));
    if (!response.ok) { const e = new Error(data.error || 'Could not update the room.'); e.status=response.status; throw e; }
    return data;
  };
  function renderRoom(room) {
    roomState = room;
    $('petRoomCoins').textContent = `🪙 ${room.coins} coins`;
    $('petRoomDaily').disabled = !room.daily_reward_available;
    $('petRoomDaily').textContent = room.daily_reward_available ? '🎁 Collect daily +20 coins' : '✓ Daily bonus collected';
    const byId = Object.fromEntries(room.catalog.map(item=>[item.id,item]));
    scene.querySelectorAll('[data-room-slot]').forEach(el=>{
      const slot = el.dataset.roomSlot, item = byId[room.equipped[slot]];
      el.textContent = item ? item.emoji : '';
      el.classList.toggle('is-empty',!item);
      el.setAttribute('aria-label',item ? `${item.name} decoration` : `${slot} area empty`);
    });
    shop.innerHTML = room.catalog.map(item=>{
      const equipped = room.equipped[item.slot] === item.id;
      const action = item.owned ? (equipped ? `<button disabled class="room-item-equipped">✓ Equipped</button>` : `<button data-room-equip="${item.id}" data-slot="${item.slot}">Equip</button>`) : `<button data-room-buy="${item.id}" ${room.coins<item.price?'disabled':''}>Unlock · ${item.price} 🪙</button>`;
      return `<article class="room-shop-item"><span class="room-item-emoji">${item.emoji}</span><div class="room-item-copy"><b>${item.name}</b><small>${item.description}</small></div>${action}</article>`;
    }).join('');
  }
  async function refresh() {
    try {
      const data = await api('/api/pet/room'); loggedIn=true; $('petRoomLogin').hidden=true; renderRoom(data.room);
    } catch(e) {
      if(e.status===401){loggedIn=false;$('petRoomLogin').hidden=false;$('petRoomCoins').textContent='🪙 Sign in';shop.innerHTML='<div class="room-shop-loading">Your own room and collection will appear after login.</div>';}
      else message.textContent=e.message;
    }
  }
  async function run(url, payload, successFallback) {
    if(busy || !loggedIn) return; busy=true; root.classList.add('is-busy');
    try { const data=await api(url,{method:'POST',body:JSON.stringify(payload||{})}); renderRoom(data.room); message.textContent=data.message||successFallback||'Room updated!'; }
    catch(e){message.textContent=e.message;}
    finally{busy=false;root.classList.remove('is-busy');}
  }
  shop.addEventListener('click',e=>{
    const buy=e.target.closest('[data-room-buy]'); if(buy){run('/api/pet/room/buy',{item_id:buy.dataset.roomBuy});return;}
    const equip=e.target.closest('[data-room-equip]'); if(equip) run('/api/pet/room/decorate',{slot:equip.dataset.slot,item_id:equip.dataset.roomEquip});
  });
  $('petRoomDaily').addEventListener('click',()=>run('/api/pet/room/daily-reward',{}));
  $('assistantToggle')?.addEventListener('click',()=>{if(document.getElementById('assistantPanel')?.classList.contains('open'))refresh();});
  window.addEventListener('skillswap:auth-changed',refresh);
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible' && loggedIn) refresh();});
  refresh();
})();
