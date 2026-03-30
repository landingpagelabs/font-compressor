(function () {
  'use strict';

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  /* ======================================================================
     State
     ====================================================================== */
  let queuedFiles = [];
  let compressedResults = [];
  let libraryData = [];
  let activeCategory = 'all';
  let searchQuery = '';
  let loadedFontFaces = new Set();
  const HISTORY_KEY = 'fontcompressor_history';

  /* ======================================================================
     Tabs
     ====================================================================== */
  $$('.tab-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var tab = btn.getAttribute('data-tab');
      $$('.tab-btn').forEach(function (b) { b.classList.remove('active'); });
      $$('.tab-content').forEach(function (c) { c.classList.remove('active'); });
      btn.classList.add('active');
      $('#tab-' + tab).classList.add('active');
      if (tab === 'library' && libraryData.length === 0) {
        loadLibrary();
      }
    });
  });

  /* ======================================================================
     COMPRESS TAB
     ====================================================================== */
  var dropZone = $('#dropZone');
  var fileInput = $('#fileInput');

  dropZone.addEventListener('dragover', function (e) {
    e.preventDefault();
    dropZone.classList.add('dragover');
  });

  dropZone.addEventListener('dragleave', function () {
    dropZone.classList.remove('dragover');
  });

  dropZone.addEventListener('drop', function (e) {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    handleFiles(e.dataTransfer.files);
  });

  fileInput.addEventListener('change', function () {
    handleFiles(fileInput.files);
    fileInput.value = '';
  });

  function handleFiles(fileList) {
    var validExts = ['.ttf', '.otf', '.woff', '.woff2'];
    var maxSize = 4500000;
    var maxFiles = 20;

    for (var i = 0; i < fileList.length; i++) {
      if (queuedFiles.length >= maxFiles) break;
      var file = fileList[i];
      var ext = '.' + file.name.split('.').pop().toLowerCase();
      if (validExts.indexOf(ext) === -1) continue;
      if (file.size > maxSize) continue;
      var isDupe = queuedFiles.some(function (f) { return f.name === file.name && f.size === file.size; });
      if (isDupe) continue;
      queuedFiles.push(file);
    }
    renderFileList();
    updateCompressButton();
  }

  function renderFileList() {
    var container = $('#fileList');
    container.innerHTML = '';
    queuedFiles.forEach(function (file, idx) {
      var item = document.createElement('div');
      item.className = 'file-item';
      item.innerHTML =
        '<span class="file-item-name">' + escapeHtml(file.name) + '</span>' +
        '<span class="file-item-size">' + formatSize(file.size) + '</span>' +
        '<button class="file-item-remove" data-idx="' + idx + '">&times;</button>';
      container.appendChild(item);
    });
    container.querySelectorAll('.file-item-remove').forEach(function (btn) {
      btn.addEventListener('click', function () {
        queuedFiles.splice(parseInt(btn.getAttribute('data-idx')), 1);
        renderFileList();
        updateCompressButton();
      });
    });
  }

  function updateCompressButton() {
    $('#compressBtn').disabled = queuedFiles.length === 0;
  }

  $('#compressBtn').addEventListener('click', function () {
    if (queuedFiles.length === 0) return;
    compressAll();
  });

  function compressAll() {
    compressedResults = [];
    var resultsList = $('#resultsList');
    resultsList.innerHTML = '';
    $('#results').style.display = '';

    var loadingEls = [];
    queuedFiles.forEach(function (file) {
      var el = document.createElement('div');
      el.className = 'result-card-loading';
      el.innerHTML = '<div class="spinner"></div> Compressing ' + escapeHtml(file.name) + '...';
      resultsList.appendChild(el);
      loadingEls.push(el);
    });

    var btn = $('#compressBtn');
    btn.disabled = true;
    btn.innerHTML = '<div class="spinner"></div> Compressing...';

    var newEntries = [];

    var promises = queuedFiles.map(function (file, idx) {
      return compressFile(file).then(function (result) {
        var now = new Date().toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' });
        if (result.duplicate) {
          loadingEls[idx].replaceWith(createDuplicateCard(result));
          saveToHistory({ filename: file.name, type: 'duplicate', slug: result.slug, size: result.sizeWoff2, date: now });
        } else {
          loadingEls[idx].replaceWith(createResultCard(result));
          compressedResults.push(result);
          newEntries.push({
            hash: result.hash,
            slug: result.slug,
            family: result.family,
            category: result.category,
            style: result.style,
            weight: result.weight,
            italic: result.italic,
            filename: result.filename,
            url: result.url,
            originalSize: result.originalSize,
            compressedSize: result.compressedSize
          });
          saveToHistory({
            filename: result.filename,
            type: result.alreadyCompressed ? 'saved' : 'compressed',
            slug: result.slug,
            size: result.compressedSize,
            savings: result.alreadyCompressed ? null : result.savings,
            date: now
          });
        }
      }).catch(function (err) {
        loadingEls[idx].innerHTML = '<span style="color:#ef4444">Failed: ' + escapeHtml(file.name) + ' — ' + escapeHtml(err.message || String(err)) + '</span>';
        loadingEls[idx].className = 'result-card-loading';
      });
    });

    Promise.all(promises).then(function () {
      btn.disabled = false;
      btn.innerHTML = 'Compress to WOFF2';
      $('#downloadAllBtn').style.display = compressedResults.length > 1 ? '' : 'none';
      renderHistory();
      if (newEntries.length > 0) {
        fetch('/api/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(newEntries)
        }).then(function () {
          return fetch('/api/library');
        }).then(function (res) { return res.json(); })
          .then(function (data) { libraryData = data; });
      }
    });
  }

  function compressFile(file) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () {
        var b64 = arrayBufferToBase64(reader.result);
        fetch('/api/compress', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            font: b64,
            filename: file.name,
            subset: 'basic-latin'
          })
        }).then(function (res) {
          if (!res.ok) {
            return res.json().then(function (data) { throw new Error(data.error || 'Server error'); });
          }
          return res.json();
        }).then(function (data) {
          if (data.duplicate) {
            resolve({
              duplicate: true,
              slug: data.slug,
              family: data.family,
              category: data.category,
              style: data.style,
              url: data.url,
              sizeWoff2: data.sizeWoff2
            });
          } else {
            var woff2Bytes = base64ToUint8Array(data.woff2);
            var blob = new Blob([woff2Bytes], { type: 'font/woff2' });
            resolve({
              duplicate: false,
              alreadyCompressed: data.alreadyCompressed || false,
              filename: data.filename,
              fontName: data.fontName,
              family: data.family,
              slug: data.slug,
              category: data.category,
              style: data.style,
              weight: data.weight,
              italic: data.italic,
              originalSize: data.originalSize,
              compressedSize: data.compressedSize,
              savings: data.savings,
              url: data.url,
              hash: data.hash,
              blob: blob
            });
          }
        }).catch(reject);
      };
      reader.onerror = function () { reject(new Error('Could not read file')); };
      reader.readAsArrayBuffer(file);
    });
  }

  function createResultCard(result) {
    var card = document.createElement('div');
    card.className = 'result-card';

    var fontUrl = URL.createObjectURL(result.blob);
    var fontFace = 'compressed-' + result.filename.replace(/[^a-zA-Z0-9]/g, '');
    var style = document.createElement('style');
    style.textContent = '@font-face { font-family: "' + fontFace + '"; src: url("' + fontUrl + '") format("woff2"); }';
    document.head.appendChild(style);

    var statsHtml;
    if (result.alreadyCompressed) {
      statsHtml =
        '<span>' + formatSize(result.compressedSize) + '</span>' +
        '<span class="result-savings" style="background:var(--success-soft);color:var(--success)">Saved to library</span>';
    } else {
      statsHtml =
        '<span>' + formatSize(result.originalSize) + ' &rarr; ' + formatSize(result.compressedSize) + '</span>' +
        '<span class="result-savings">' + result.savings + '% smaller</span>';
    }

    card.innerHTML =
      '<div class="result-card-top">' +
        '<span class="result-card-name">' + escapeHtml(result.filename) + '</span>' +
        '<div class="result-card-stats">' + statsHtml + '</div>' +
      '</div>' +
      '<div class="result-preview" style="font-family:\'' + fontFace + '\',sans-serif">The quick brown fox jumps over the lazy dog</div>' +
      '<div class="result-card-actions">' +
        '<button class="download-btn">&#8595; Download WOFF2</button>' +
      '</div>';

    card.querySelector('.download-btn').addEventListener('click', function () {
      downloadBlob(result.blob, result.filename);
    });

    return card;
  }

  function createDuplicateCard(result) {
    var card = document.createElement('div');
    card.className = 'result-card';
    var deepLink = window.location.origin + '/#' + result.slug;

    var catLabel = (result.category || 'sans-serif').replace('-', ' ');
    catLabel = catLabel.charAt(0).toUpperCase() + catLabel.slice(1);

    card.innerHTML =
      '<div class="result-card-top">' +
        '<span class="result-card-name">' + escapeHtml(result.family + ' ' + result.style) + '</span>' +
        '<span class="result-savings" style="background:var(--accent-soft);color:var(--accent)">Already in library</span>' +
      '</div>' +
      '<div class="dupe-info">' +
        '<span class="font-card-badge">' + catLabel + '</span> ' +
        '<span>' + formatSize(result.sizeWoff2) + '</span>' +
      '</div>' +
      '<div class="result-card-actions" style="gap:8px">' +
        '<button class="download-btn dupe-link-btn">Copy link</button>' +
        '<button class="download-btn dupe-go-btn">Go to library</button>' +
      '</div>';

    card.querySelector('.dupe-link-btn').addEventListener('click', function () {
      navigator.clipboard.writeText(deepLink).then(function () {
        card.querySelector('.dupe-link-btn').textContent = 'Copied!';
        setTimeout(function () { card.querySelector('.dupe-link-btn').textContent = 'Copy link'; }, 1500);
      });
    });

    card.querySelector('.dupe-go-btn').addEventListener('click', function () {
      window.location.hash = result.slug;
    });

    return card;
  }

  $('#downloadAllBtn').addEventListener('click', function () {
    if (compressedResults.length === 0) return;
    var zip = new JSZip();
    compressedResults.forEach(function (r) { zip.file(r.filename, r.blob); });
    zip.generateAsync({ type: 'blob' }).then(function (content) {
      downloadBlob(content, 'fonts-woff2.zip');
    });
  });

  /* ======================================================================
     HISTORY
     ====================================================================== */

  function getHistory() {
    try { return JSON.parse(localStorage.getItem(HISTORY_KEY)) || []; }
    catch (e) { return []; }
  }

  function saveToHistory(entry) {
    var history = getHistory();
    history.unshift(entry);
    if (history.length > 200) history = history.slice(0, 200);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
  }

  function renderHistory() {
    var list = $('#historyList');
    var history = getHistory();
    list.innerHTML = '';

    if (history.length === 0) {
      list.innerHTML = '<div class="empty-state"><span class="empty-state-icon">&#128196;</span>No uploads yet.</div>';
      return;
    }

    history.forEach(function (item) {
      var row = document.createElement('div');
      row.className = 'history-item';

      var badgeClass = item.type === 'compressed' ? 'history-badge-compressed' :
                       item.type === 'saved' ? 'history-badge-saved' : 'history-badge-duplicate';
      var badgeText = item.type === 'compressed' ? 'Compressed' :
                      item.type === 'saved' ? 'Saved' : 'Duplicate';

      var metaParts = [];
      if (item.size) metaParts.push(formatSize(item.size));
      if (item.savings) metaParts.push(item.savings + '% smaller');
      if (item.date) metaParts.push(item.date);

      row.innerHTML =
        '<div class="history-item-info">' +
          '<div class="history-item-name">' + escapeHtml(item.filename) + '</div>' +
          '<div class="history-item-meta">' + metaParts.join(' &middot; ') + '</div>' +
        '</div>' +
        '<div class="history-item-actions">' +
          '<span class="history-badge ' + badgeClass + '">' + badgeText + '</span>' +
          (item.slug ? '<button class="download-btn history-link-btn" data-slug="' + item.slug + '">&#128279;</button>' : '') +
        '</div>';

      list.appendChild(row);
    });

    list.querySelectorAll('.history-link-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var deepLink = window.location.origin + '/#' + btn.getAttribute('data-slug');
        navigator.clipboard.writeText(deepLink).then(function () {
          btn.textContent = 'Copied!';
          setTimeout(function () { btn.innerHTML = '&#128279;'; }, 1500);
        });
      });
    });
  }

  $('#clearHistoryBtn').addEventListener('click', function () {
    localStorage.removeItem(HISTORY_KEY);
    renderHistory();
  });

  /* ======================================================================
     LIBRARY TAB — grouped by family, each style listed with weight + download
     ====================================================================== */

  function loadLibrary(scrollToSlug) {
    fetch('/api/library')
      .then(function (res) { return res.json(); })
      .then(function (data) {
        libraryData = data;
        renderLibrary();
        if (scrollToSlug) {
          scrollToFont(scrollToSlug);
        }
      })
      .catch(function () {
        $('#fontGrid').innerHTML = '<div class="empty-state"><span class="empty-state-icon">&#9888;</span>Could not load font library.</div>';
      });
  }

  function scrollToFont(slug) {
    var el = document.getElementById(slug);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.style.boxShadow = '0 0 0 2px var(--accent)';
      setTimeout(function () { el.style.boxShadow = ''; }, 2000);
    }
  }

  // Deep link: if URL has a hash, switch to Library tab and scroll to font
  function handleDeepLink() {
    var hash = window.location.hash.replace('#', '');
    if (!hash) return;
    // Switch to library tab
    $$('.tab-btn').forEach(function (b) { b.classList.remove('active'); });
    $$('.tab-content').forEach(function (c) { c.classList.remove('active'); });
    $('[data-tab="library"]').classList.add('active');
    $('#tab-library').classList.add('active');
    // Load library and scroll
    if (libraryData.length === 0) {
      loadLibrary(hash);
    } else {
      scrollToFont(hash);
    }
  }

  handleDeepLink();
  renderHistory();
  window.addEventListener('hashchange', handleDeepLink);

  $('#librarySearch').addEventListener('input', function () {
    searchQuery = this.value.toLowerCase().trim();
    renderLibrary();
  });

  $('#categoryPills').addEventListener('click', function (e) {
    if (!e.target.classList.contains('pill')) return;
    activeCategory = e.target.getAttribute('data-category');
    $$('#categoryPills .pill').forEach(function (p) { p.classList.remove('active'); });
    e.target.classList.add('active');
    renderLibrary();
  });

  $('#previewText').addEventListener('input', function () {
    var text = this.value || 'The quick brown fox jumps over the lazy dog';
    $$('.font-card-preview').forEach(function (el) {
      el.textContent = text;
    });
  });

  function renderLibrary() {
    var grid = $('#fontGrid');
    grid.innerHTML = '';

    var filtered = libraryData.filter(function (font) {
      if (activeCategory !== 'all' && font.category !== activeCategory) return false;
      if (searchQuery && font.family.toLowerCase().indexOf(searchQuery) === -1) return false;
      return true;
    });

    var totalStyles = filtered.reduce(function (sum, f) { return sum + f.variants.length; }, 0);
    $('#fontCount').textContent = filtered.length + ' famil' + (filtered.length !== 1 ? 'ies' : 'y') + ', ' + totalStyles + ' style' + (totalStyles !== 1 ? 's' : '');

    if (filtered.length === 0) {
      grid.innerHTML = '<div class="empty-state"><span class="empty-state-icon">&#128270;</span>No fonts match your search.</div>';
      return;
    }

    var previewText = $('#previewText').value || 'The quick brown fox jumps over the lazy dog';

    filtered.forEach(function (font) {
      var card = document.createElement('div');
      card.className = 'font-family-card';
      card.id = font.slug;

      var categoryLabel = font.category.replace('-', ' ');
      categoryLabel = categoryLabel.charAt(0).toUpperCase() + categoryLabel.slice(1);

      // Use the regular variant for the main preview
      var previewVariant = font.variants.find(function (v) { return v.style === 'Regular'; }) || font.variants[0];
      var previewFontId = 'lib-' + previewVariant.file.replace(/[^a-zA-Z0-9]/g, '');

      // Header + preview
      var header = document.createElement('div');
      header.className = 'font-family-header';
      header.innerHTML =
        '<div class="font-family-title">' +
          '<span class="font-card-name">' + escapeHtml(font.family) + '</span>' +
          '<span class="font-card-badge">' + categoryLabel + '</span>' +
        '</div>' +
        '<div class="font-card-preview" style="font-family:\'' + previewFontId + '\',sans-serif">' + escapeHtml(previewText) + '</div>';
      card.appendChild(header);

      // Variant list
      var list = document.createElement('div');
      list.className = 'variant-list';

      font.variants.forEach(function (v) {
        var fontFaceId = 'lib-' + v.file.replace(/[^a-zA-Z0-9]/g, '');
        var row = document.createElement('div');
        row.className = 'variant-row';
        row.innerHTML =
          '<span class="variant-style">' + escapeHtml(v.style) + '</span>' +
          '<span class="variant-weight">' + v.weight + '</span>' +
          '<span class="variant-size">' + formatSize(v.sizeWoff2) + '</span>' +
          '<button class="download-btn variant-dl">&#8595;</button>';

        row.querySelector('.variant-dl').addEventListener('click', function (e) {
          e.stopPropagation();
          triggerDownload(v.url || '/fonts/' + v.file, v.file);
        });

        // Lazy load each variant's font face
        lazyLoadFont(row, fontFaceId, v.url || '/fonts/' + v.file, v.weight, v.italic ? 'italic' : 'normal');

        list.appendChild(row);
      });

      card.appendChild(list);

      // Download All button
      var footer = document.createElement('div');
      footer.className = 'font-family-footer';
      var dlAllBtn = document.createElement('button');
      dlAllBtn.className = 'download-all-family-btn';
      dlAllBtn.innerHTML = '&#8595; Download All (' + font.variants.length + ' style' + (font.variants.length !== 1 ? 's' : '') + ')';
      dlAllBtn.addEventListener('click', function () {
        if (font.variants.length === 1) {
          var v0 = font.variants[0];
          triggerDownload(v0.url || '/fonts/' + v0.file, v0.file);
        } else {
          var zip = new JSZip();
          var fetches = font.variants.map(function (v) {
            return fetch(v.url || '/fonts/' + v.file)
              .then(function (res) { return res.blob(); })
              .then(function (blob) { zip.file(v.file, blob); });
          });
          Promise.all(fetches).then(function () {
            zip.generateAsync({ type: 'blob' }).then(function (content) {
              downloadBlob(content, font.slug + '-woff2.zip');
            });
          });
        }
      });
      var shareBtn = document.createElement('button');
      shareBtn.className = 'share-font-btn';
      shareBtn.innerHTML = '&#128279; Share';
      shareBtn.addEventListener('click', function () {
        var deepLink = window.location.origin + '/#' + font.slug;
        navigator.clipboard.writeText(deepLink).then(function () {
          shareBtn.textContent = 'Copied!';
          setTimeout(function () { shareBtn.innerHTML = '&#128279; Share'; }, 1500);
        });
      });
      footer.appendChild(shareBtn);
      footer.appendChild(dlAllBtn);
      card.appendChild(footer);

      // Lazy load preview font
      lazyLoadFont(card, previewFontId, previewVariant.url || '/fonts/' + previewVariant.file, previewVariant.weight, previewVariant.italic ? 'italic' : 'normal');

      grid.appendChild(card);
    });
  }

  function lazyLoadFont(card, fontFaceId, file, weight, fontStyle) {
    if (loadedFontFaces.has(fontFaceId)) return;

    if ('IntersectionObserver' in window) {
      var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            injectFontFace(fontFaceId, file, weight, fontStyle);
            observer.unobserve(card);
          }
        });
      }, { rootMargin: '200px' });
      observer.observe(card);
    } else {
      injectFontFace(fontFaceId, file, weight, fontStyle);
    }
  }

  function injectFontFace(fontFaceId, fontUrl, weight, fontStyle) {
    if (loadedFontFaces.has(fontFaceId)) return;
    loadedFontFaces.add(fontFaceId);
    var style = document.createElement('style');
    style.textContent = '@font-face { font-family: "' + fontFaceId + '"; src: url("' + fontUrl + '") format("woff2"); font-weight: ' + weight + '; font-style: ' + fontStyle + '; font-display: swap; }';
    document.head.appendChild(style);
  }

  /* ======================================================================
     Utilities
     ====================================================================== */

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    var kb = bytes / 1024;
    if (kb < 1024) return kb.toFixed(1) + ' KB';
    return (kb / 1024).toFixed(2) + ' MB';
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function arrayBufferToBase64(buffer) {
    var bytes = new Uint8Array(buffer);
    var binary = '';
    for (var i = 0; i < bytes.byteLength; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
  }

  function base64ToUint8Array(b64) {
    var binary = atob(b64);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
  }

  function downloadBlob(blob, filename) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function triggerDownload(url, filename) {
    var a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

})();
