
// Simple modal functions (not using Bootstrap JS)
function openModal(id){ document.getElementById(id).classList.add('show'); }
function closeModal(id){ document.getElementById(id).classList.remove('show'); }

// Add candidate dynamically on create page
function addCandidate(){
  const list = document.getElementById('candidatesList');
  const idx = list.children.length + 1;
  const card = document.createElement('div');
  card.className = 'candidate-card mb-3';
  card.innerHTML = `
    <img src="/static/img/candidate${(idx%3)+1}.png" alt="candidate">
    <div style="flex:1">
      <h5>Nama Kandidat ${idx}</h5>
      <p><strong>Visi:</strong> Contoh visi singkat.</p>
      <p><strong>Misi:</strong> Contoh misi singkat.</p>
    </div>
    <div>
      <button class="btn btn-outline-primary mb-2" onclick="openModal('modalCV')">Lihat CV</button><br>
      <button class="btn btn-danger" onclick="openModal('modalHapus')">Hapus</button>
    </div>
  `;
  list.appendChild(card);
  closeModal('modalTambah');
}

// confirm delete - simple behavior to remove last candidate for demo
function confirmHapus(){
  const list = document.getElementById('candidatesList');
  if(list.lastElementChild) list.removeChild(list.lastElementChild);
  closeModal('modalHapus');
}

// on vote confirm, redirect to result
function confirmVote(){
  closeModal('modalVoteConfirm');
  window.location.href = '/result';
}
