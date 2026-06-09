const manifestUrl = new URL('manifest.json', window.location.href);
const list = document.querySelector('#catalog-list');
const search = document.querySelector('#search');
const template = document.querySelector('#item-template');
let items = [];

function absoluteUrl(url) {
  return new URL(url, manifestUrl).href;
}

function render(filter = '') {
  const query = filter.trim().toLowerCase();
  list.innerHTML = '';
  const filtered = items.filter((item) => {
    const haystack = [item.name, item.description, item.type, ...(item.tags || [])].join(' ').toLowerCase();
    return !query || haystack.includes(query);
  });

  if (!filtered.length) {
    list.innerHTML = '<p class="empty-state">No workflows match this search.</p>';
    return;
  }

  filtered.forEach((item) => {
    const row = template.content.firstElementChild.cloneNode(true);
    const icon = row.querySelector('.workflow-icon');
    const title = row.querySelector('h3');
    const description = row.querySelector('p');
    const type = row.querySelector('.workflow-type');
    const tags = row.querySelector('.tags');
    const copy = row.querySelector('.copy-url');
    const link = row.querySelector('.package-link');
    const packageUrl = absoluteUrl(item.package_url);

    icon.src = absoluteUrl(item.icon || 'icons/ai-mime-icon.png');
    icon.alt = `${item.name} icon`;
    title.textContent = item.name;
    description.textContent = item.description;
    type.textContent = item.type || 'workflow';
    tags.innerHTML = '';
    (item.tags || []).forEach((tag) => {
      const span = document.createElement('span');
      span.textContent = tag;
      tags.appendChild(span);
    });
    link.href = packageUrl;
    link.textContent = 'Package';
    copy.addEventListener('click', async () => {
      await navigator.clipboard.writeText(packageUrl);
      copy.textContent = 'Copied';
      setTimeout(() => { copy.textContent = 'Copy URL'; }, 1300);
    });
    list.appendChild(row);
  });
}

async function loadManifest() {
  try {
    const response = await fetch(manifestUrl, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Manifest request failed: ${response.status}`);
    const manifest = await response.json();
    items = Array.isArray(manifest.items) ? manifest.items : [];
    render();
  } catch (error) {
    list.innerHTML = `<p class="empty-state">Could not load marketplace manifest: ${error.message}</p>`;
  }
}

search.addEventListener('input', () => render(search.value));
loadManifest();
