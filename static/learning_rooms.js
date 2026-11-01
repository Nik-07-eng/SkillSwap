/* SkillSwap Learning Rooms: public room discovery, member-only discussion and Jitsi live meetings. */
(()=>{
  const $ = (s, root=document) => root.querySelector(s);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const apiRoom = async (path, options={}) => {
    const response = await fetch(path, {credentials:'include', cache:'no-store', ...options,
      headers:{...(options.body?{'Content-Type':'application/json'}:{}), ...(options.headers||{})}});
    let data={}; try{data=await response.json()}catch{}
    if(!response.ok){const error=new Error(data.error||'Could not complete that action.');error.status=response.status;throw error;}
    return data;
  };
  let rooms=[], activeRoom=null, lastMessageId=0, pollTimer=null, refreshTimer=null;

  function roomCard(room){
    const percent=Math.min(100,Math.round((room.member_count/room.capacity)*100));
    const action=room.joined?'Open room':'Join room';
    const badge=room.is_host?'YOUR ROOM':room.joined?'JOINED':'OPEN';
    return `<article class="learning-room-card">
      <div class="room-card-top"><span class="room-topic-pill">${esc(room.topic)}</span><span class="room-open-badge"><i></i>${badge}</span></div>
      <h3>${esc(room.title)}</h3><p class="room-card-description">${esc(room.description||'A friendly peer-learning space. Join the conversation and learn by sharing.')}</p>
      <div class="room-card-meta"><span>◉ ${esc(room.level)}</span><span>♙ Hosted by ${esc(room.host_name)}</span></div>
      <div class="room-capacity-row"><span>${room.member_count} / ${room.capacity} learners</span><b>${percent}%</b></div><div class="room-capacity-track"><span style="width:${percent}%"></span></div>
      <div class="room-card-footer"><small>Created ${room.created_at?new Date(room.created_at).toLocaleDateString(): 'recently'}</small><button class="primary-button room-enter-btn" data-room-enter="${room.id}" ${!room.joined&&room.member_count>=room.capacity?'disabled':''}>${room.member_count>=room.capacity&&!room.joined?'Room full':action} ↗</button></div>
    </article>`;
  }
  function renderRooms(){
    const grid=$('#learningRoomsGrid'); if(!grid)return;
    const query=($('#roomSearch')?.value||'').trim().toLowerCase();
    const level=$('#roomLevelFilter')?.value||'';
    const filtered=rooms.filter(r=>(!query||`${r.title} ${r.topic} ${r.description} ${r.host_name}`.toLowerCase().includes(query))&&(!level||r.level===level));
    $('#roomNavCount').textContent=rooms.length;
    grid.innerHTML=filtered.length?filtered.map(roomCard).join(''):`<div class="empty-state rooms-empty"><span>◉</span><b>No rooms found yet</b><p>${rooms.length?'Try another search or experience level.':'Create the first learning room and invite the community.'}</p><button class="secondary-button" id="emptyCreateRoom">＋ Create a room</button></div>`;
    $('#emptyCreateRoom')?.addEventListener('click',openCreateRoom);
    grid.querySelectorAll('[data-room-enter]').forEach(btn=>btn.addEventListener('click',()=>enterRoom(Number(btn.dataset.roomEnter))));
  }
  async function loadLearningRooms(){
    const grid=$('#learningRoomsGrid'); if(!grid)return;
    grid.innerHTML='<div class="empty-state">Finding active learning spaces…</div>';
    try{const data=await apiRoom('/api/rooms');rooms=data.rooms||[];renderRooms();}
    catch(error){grid.innerHTML=`<div class="empty-state">${esc(error.message)}<br><br><button class="secondary-button" id="retryRooms">Try again ↻</button></div>`;$('#retryRooms')?.addEventListener('click',loadLearningRooms);}
  }
  window.loadLearningRooms=loadLearningRooms;
  function openCreateRoom(){if(!window.currentUser && !document.querySelector('#authModal')){} if(!currentUser){openAuth('login');return;}openModal('createRoomModal');}
  function stopPolling(){if(pollTimer)clearInterval(pollTimer);pollTimer=null;}
  function showRoomWorkspace(room){
    activeRoom=room;lastMessageId=0;$('#roomWorkspace').hidden=false;
    $('#roomWorkspaceTitle').textContent=room.title;
    $('#roomWorkspaceMeta').textContent=`${room.topic} · ${room.member_count}/${room.capacity} learners · Hosted by ${room.host_name}`;
    $('#roomVideoLink').href=room.meeting_url;
    $('#roomVideoLink').setAttribute('aria-label',`Join live video meeting for ${room.title}`);
    $('#closeRoomBtn').hidden=!room.is_host;
    $('#leaveRoomBtn').hidden=room.is_host;
    $('#roomMessages').innerHTML='<p class="muted room-chat-welcome">Welcome! Introduce yourself and share what you hope to learn today. ✨</p>';
    $('#roomMessageInput').disabled=room.status!=='open';
    $('#roomMessageForm').querySelector('button').disabled=room.status!=='open';
    $('#roomWorkspace').scrollIntoView({behavior:'smooth',block:'start'});
    fetchMessages();stopPolling();pollTimer=setInterval(()=>{if(activeRoom&&$('#view-rooms')?.classList.contains('active'))fetchMessages()},4500);
  }
  async function enterRoom(id){
    if(!currentUser){openAuth('login');return;}
    const room=rooms.find(r=>r.id===id);if(!room)return;
    try{
      let result;
      if(room.joined){result={room};}
      else{result=await apiRoom(`/api/rooms/${id}/join`,{method:'POST'});}
      const updated=result.room;const index=rooms.findIndex(r=>r.id===id);if(index>=0)rooms[index]=updated;
      renderRooms();showRoomWorkspace(updated);if(window.questRefresh)window.questRefresh();toast(updated.joined?'Room opened. Welcome back!':'You joined the learning room.');
    }catch(error){toast(error.message,true);await loadLearningRooms();}
  }
  async function fetchMessages(){
    if(!activeRoom)return;
    try{
      const data=await apiRoom(`/api/rooms/${activeRoom.id}/messages?after=${lastMessageId}`);
      const box=$('#roomMessages');
      (data.messages||[]).forEach(message=>{
        lastMessageId=Math.max(lastMessageId,message.id);
        const item=document.createElement('article');item.className='room-message'+(message.sender_id===currentUser?.id?' mine':'');
        const head=document.createElement('div');head.className='room-message-head';
        const who=document.createElement('b');who.textContent=message.sender_id===currentUser?.id?'You':message.sender_name;
        const when=document.createElement('time');when.textContent=message.created_at?new Date(message.created_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):'';
        const body=document.createElement('p');body.textContent=message.body;
        head.append(who,when);item.append(head,body);box.append(item);
      });
      if((data.messages||[]).length)box.scrollTop=box.scrollHeight;
    }catch(error){if(error.status===403){stopPolling();toast('Your room membership is no longer active.',true);}}
  }
  $('#openCreateRoom')?.addEventListener('click',openCreateRoom);
  $('#refreshRooms')?.addEventListener('click',loadLearningRooms);
  $('#roomSearch')?.addEventListener('input',renderRooms);
  $('#roomLevelFilter')?.addEventListener('change',renderRooms);
  $('#createRoomForm')?.addEventListener('submit',async event=>{
    event.preventDefault();if(!currentUser){openAuth('login');return;}
    const form=event.currentTarget,button=$('#createRoomSubmit');button.disabled=true;button.textContent='Creating room…';
    const values=Object.fromEntries(new FormData(form).entries());values.capacity=Number(values.capacity);
    try{const data=await apiRoom('/api/rooms',{method:'POST',body:JSON.stringify(values)});closeModal('createRoomModal');form.reset();await loadLearningRooms();showRoomWorkspace(data.room);if(window.questRefresh)window.questRefresh();toast('Your learning room is ready. Invite others to join!');}
    catch(error){toast(error.message,true)}finally{button.disabled=false;button.textContent='Create learning room ↗';}
  });
  $('#roomMessageForm')?.addEventListener('submit',async event=>{
    event.preventDefault();if(!activeRoom)return;const input=$('#roomMessageInput'),body=input.value.trim();if(!body)return;
    const button=event.currentTarget.querySelector('button');button.disabled=true;
    try{await apiRoom(`/api/rooms/${activeRoom.id}/messages`,{method:'POST',body:JSON.stringify({body})});input.value='';await fetchMessages();if(window.questRefresh)window.questRefresh();}
    catch(error){toast(error.message,true)}finally{button.disabled=false;input.focus();}
  });
  $('#leaveRoomBtn')?.addEventListener('click',async()=>{
    if(!activeRoom)return;try{await apiRoom(`/api/rooms/${activeRoom.id}/leave`,{method:'POST'});toast('You left the learning room.');activeRoom=null;stopPolling();$('#roomWorkspace').hidden=true;await loadLearningRooms();}catch(error){toast(error.message,true)}
  });
  $('#closeRoomBtn')?.addEventListener('click',async()=>{
    if(!activeRoom||!confirm('Close this learning room? Members will no longer be able to post messages.'))return;
    try{await apiRoom(`/api/rooms/${activeRoom.id}/close`,{method:'POST'});toast('Learning room closed.');activeRoom=null;stopPolling();$('#roomWorkspace').hidden=true;await loadLearningRooms();}catch(error){toast(error.message,true)}
  });
  document.addEventListener('click',event=>{const close=event.target.closest('[data-close="createRoomModal"]');if(close)closeModal('createRoomModal');});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stopPolling();else if(activeRoom&&$('#view-rooms')?.classList.contains('active')){fetchMessages();pollTimer=setInterval(()=>{if(activeRoom&&$('#view-rooms')?.classList.contains('active'))fetchMessages()},4500);}});
  refreshTimer=setInterval(()=>{if($('#view-rooms')?.classList.contains('active'))loadLearningRooms();},30000);
})();
