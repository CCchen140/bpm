"""图片网格 Web 页面 HTML 生成器"""

def build_image_grid_html() -> str:
    """生成图片网格页面 HTML（复用数据图表的 dark 主题）"""
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>图片网格</title>
  <style>
    /* ========== 复用数据图表的 CSS 变量 ========== */
    :root {
      --bg: #0c0e1a;
      --scene-bg: #080a14;
      --primary: #3B82F6;
      --scene-gradient:
        radial-gradient(ellipse 110% 80% at 8% 0%, rgba(59,130,246,0.14) 0%, transparent 58%),
        radial-gradient(ellipse 90% 70% at 92% 4%, rgba(139,92,246,0.12) 0%, transparent 56%),
        radial-gradient(ellipse 120% 90% at 50% 110%, rgba(16,185,129,0.08) 0%, transparent 62%),
        linear-gradient(168deg, #0d1020 0%, #0a0c18 50%, #0e1024 100%);
      --text: #94a3b8;
      --text-title: #e2e8f0;
      --text-muted: rgba(148,163,184,0.56);
      --border: rgba(255,255,255,0.08);
      --card-bg: rgba(16,20,38,0.82);
      --card-shadow: 0 1px 2px rgba(0,0,0,0.24), 0 4px 12px rgba(0,0,0,0.18);
      --hover-bg: rgba(59,130,246,0.12);
      --selected-bg: rgba(59,130,246,0.25);
      --radius-sm: 6px;
      --radius-md: 10px;
    }
    
    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }
    
    body {
      font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
      background: var(--scene-gradient);
      color: var(--text);
      overflow: hidden;
      height: 100vh;
    }
    
    /* ========== 主容器 ========== */
    #app {
      display: flex;
      flex-direction: column;
      height: 100vh;
    }
    
    /* ========== 工具栏 ========== */
    .toolbar {
      background: var(--card-bg);
      border-bottom: 1px solid var(--border);
      padding: 8px 16px;
      display: flex;
      align-items: center;
      gap: 12px;
      backdrop-filter: blur(10px);
    }
    
    .toolbar-group {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    
    .toolbar-separator {
      width: 1px;
      height: 24px;
      background: var(--border);
      margin: 0 4px;
    }
    
    .toolbar-btn {
      background: transparent;
      border: 1px solid var(--border);
      color: var(--text);
      padding: 6px 12px;
      border-radius: var(--radius-sm);
      cursor: pointer;
      font-size: 13px;
      transition: all 0.2s;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    
    .toolbar-btn:hover {
      background: var(--hover-bg);
      border-color: var(--primary);
      color: var(--text-title);
    }
    
    .toolbar-btn.active {
      background: var(--primary);
      border-color: var(--primary);
      color: white;
    }
    
    .toolbar-label {
      color: var(--text-muted);
      font-size: 12px;
      margin-right: 4px;
    }
    
    .toolbar-slider {
      width: 120px;
      height: 4px;
      background: var(--border);
      border-radius: 2px;
      position: relative;
      cursor: pointer;
    }
    
    .toolbar-slider-fill {
      height: 100%;
      background: var(--primary);
      border-radius: 2px;
      position: relative;
    }
    
    .toolbar-slider-thumb {
      position: absolute;
      right: -6px;
      top: 50%;
      transform: translateY(-50%);
      width: 12px;
      height: 12px;
      background: white;
      border: 2px solid var(--primary);
      border-radius: 50%;
      cursor: grab;
    }
    
    .toolbar-slider-thumb:active {
      cursor: grabbing;
    }
    
    /* ========== 内容区域 ========== */
    .content {
      flex: 1;
      overflow: auto;
      padding: 16px;
    }
    
    /* 自定义滚动条 */
    .content::-webkit-scrollbar {
      width: 10px;
      height: 10px;
    }
    
    .content::-webkit-scrollbar-track {
      background: rgba(0,0,0,0.2);
    }
    
    .content::-webkit-scrollbar-thumb {
      background: rgba(255,255,255,0.15);
      border-radius: 5px;
    }
    
    .content::-webkit-scrollbar-thumb:hover {
      background: rgba(255,255,255,0.25);
    }
    
    /* ========== 图片网格 ========== */
    .image-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 16px;
      padding: 8px;
    }
    
    .image-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      overflow: hidden;
      cursor: pointer;
      transition: all 0.25s cubic-bezier(0.22, 0.61, 0.36, 1);
      position: relative;
      box-shadow: var(--card-shadow);
    }
    
    .image-card:hover {
      transform: translateY(-4px);
      box-shadow: 0 8px 24px rgba(0,0,0,0.4);
      border-color: var(--primary);
    }
    
    .image-card.selected {
      border-color: var(--primary);
      box-shadow: 0 0 0 2px var(--primary);
    }
    
    .image-card-thumb {
      width: 100%;
      aspect-ratio: 1;
      object-fit: cover;
      background: var(--scene-bg);
      display: block;
    }
    
    .image-card-info {
      padding: 10px;
      background: rgba(0,0,0,0.3);
      backdrop-filter: blur(8px);
    }
    
    .image-card-species {
      color: var(--text-title);
      font-size: 13px;
      font-weight: 500;
      margin-bottom: 4px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    
    .image-card-meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 11px;
      color: var(--text-muted);
    }
    
    .image-card-rating {
      color: #fbbf24;
    }
    
    .image-card-label {
      position: absolute;
      top: 8px;
      right: 8px;
      width: 20px;
      height: 20px;
      border-radius: 50%;
      border: 2px solid white;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    }
    
    .image-card-favorite {
      position: absolute;
      top: 8px;
      left: 8px;
      color: #ef4444;
      font-size: 18px;
      filter: drop-shadow(0 2px 4px rgba(0,0,0,0.5));
    }
    
    /* ========== 加载状态 ========== */
    .loading {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      height: 100%;
      color: var(--text-muted);
    }
    
    .loading-spinner {
      width: 40px;
      height: 40px;
      border: 3px solid var(--border);
      border-top-color: var(--primary);
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      margin-bottom: 16px;
    }
    
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
    
    /* ========== 空状态 ========== */
    .empty-state {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      height: 100%;
      color: var(--text-muted);
    }
    
    .empty-icon {
      font-size: 64px;
      margin-bottom: 16px;
      opacity: 0.5;
    }
    
    /* ========== 状态栏 ========== */
    .statusbar {
      background: var(--card-bg);
      border-top: 1px solid var(--border);
      padding: 6px 16px;
      font-size: 12px;
      color: var(--text-muted);
      display: flex;
      align-items: center;
      gap: 16px;
    }
    
    /* ========== 选择框 ========== */
    .selection-box {
      position: fixed;
      border: 2px solid var(--primary);
      background: rgba(59,130,246,0.1);
      pointer-events: none;
      z-index: 1000;
    }
    
    /* ========== 响应式 ========== */
    @media (max-width: 768px) {
      .image-grid {
        grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
        gap: 12px;
      }
      
      .toolbar {
        flex-wrap: wrap;
        padding: 8px;
      }
    }
  </style>
</head>
<body>
  <div id="app">
    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="toolbar-group">
        <button class="toolbar-btn" onclick="refreshImages()">
          <span>🔄</span>
          <span>刷新</span>
        </button>
        <button class="toolbar-btn" onclick="selectAll()">
          <span>☑️</span>
          <span>全选</span>
        </button>
        <button class="toolbar-btn" onclick="clearSelection()">
          <span>⬜</span>
          <span>取消选择</span>
        </button>
      </div>
      
      <div class="toolbar-separator"></div>
      
      <div class="toolbar-group">
        <span class="toolbar-label">缩略图大小:</span>
        <div class="toolbar-slider" id="sizeSlider">
          <div class="toolbar-slider-fill" id="sizeSliderFill">
            <div class="toolbar-slider-thumb" id="sizeSliderThumb"></div>
          </div>
        </div>
        <span id="sizeValue" style="color: var(--text); min-width: 40px;">180px</span>
      </div>
      
      <div class="toolbar-separator"></div>
      
      <div class="toolbar-group">
        <button class="toolbar-btn" id="viewModeBtn" onclick="toggleViewMode()">
          <span>📋</span>
          <span id="viewModeText">显示信息</span>
        </button>
      </div>
    </div>
    
    <!-- 内容区域 -->
    <div class="content" id="content">
      <div class="loading" id="loading">
        <div class="loading-spinner"></div>
        <div>正在加载图片...</div>
      </div>
      
      <div class="image-grid" id="imageGrid" style="display: none;"></div>
      
      <div class="empty-state" id="emptyState" style="display: none;">
        <div class="empty-icon">📷</div>
        <div>暂无图片</div>
      </div>
    </div>
    
    <!-- 状态栏 -->
    <div class="statusbar">
      <span id="statusTotal">总数: 0</span>
      <span>|</span>
      <span id="statusSelected">已选择: 0</span>
      <span>|</span>
      <span id="statusLoaded">已加载: 0</span>
    </div>
  </div>
  
  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
  <script>
    // ========== 全局变量 ==========
    let bridge = null;
    let images = [];
    let selectedIndices = new Set();
    let thumbnailSize = 180;
    let showInfo = true;
    let isLoading = false;
    
    // ========== 初始化 WebChannel ==========
    new QWebChannel(qt.webChannelTransport, function(channel) {
      bridge = channel.objects.bridge;
      console.log('Bridge 连接成功');
      
      // 监听后端推送
      bridge.imagesUpdated.connect(function() {
        console.log('收到图片更新通知');
        loadImages();
      });
      
      // 加载初始数据
      loadImages();
    });
    
    // ========== 加载图片列表 ==========
    async function loadImages() {
      if (isLoading) return;
      isLoading = true;
      
      showLoading();
      
      try {
        const response = await callBridge('getImages', JSON.stringify({
          page: 1,
          pageSize: 500
        }));
        
        images = response.images || [];
        renderImages();
        updateStatus();
      } catch (error) {
        console.error('加载图片失败:', error);
        showEmpty();
      } finally {
        isLoading = false;
      }
    }
    
    // ========== 渲染图片网格 ==========
    function renderImages() {
      const grid = document.getElementById('imageGrid');
      const loading = document.getElementById('loading');
      const empty = document.getElementById('emptyState');
      
      if (images.length === 0) {
        showEmpty();
        return;
      }
      
      loading.style.display = 'none';
      empty.style.display = 'none';
      grid.style.display = 'grid';
      
      // 更新网格列宽
      grid.style.gridTemplateColumns = `repeat(auto-fill, minmax(${thumbnailSize}px, 1fr))`;
      
      // 清空现有内容
      grid.innerHTML = '';
      
      // 渲染图片卡片
      images.forEach((img, index) => {
        const card = createImageCard(img, index);
        grid.appendChild(card);
      });
      
      // 异步加载缩略图
      loadThumbnails();
    }
    
    // ========== 创建图片卡片 ==========
    function createImageCard(img, index) {
      const card = document.createElement('div');
      card.className = 'image-card';
      card.dataset.index = index;
      
      if (selectedIndices.has(index)) {
        card.classList.add('selected');
      }
      
      // 缩略图
      const thumb = document.createElement('img');
      thumb.className = 'image-card-thumb';
      thumb.dataset.path = img.file_path;
      thumb.alt = img.species || '未识别';
      card.appendChild(thumb);
      
      // 收藏标记
      if (img.is_favorite) {
        const fav = document.createElement('div');
        fav.className = 'image-card-favorite';
        fav.textContent = '❤️';
        card.appendChild(fav);
      }
      
      // 色标
      if (img.label) {
        const label = document.createElement('div');
        label.className = 'image-card-label';
        label.style.background = getLabelColor(img.label);
        card.appendChild(label);
      }
      
      // 信息区域
      if (showInfo) {
        const info = document.createElement('div');
        info.className = 'image-card-info';
        
        const species = document.createElement('div');
        species.className = 'image-card-species';
        species.textContent = img.species || '未识别';
        info.appendChild(species);
        
        const meta = document.createElement('div');
        meta.className = 'image-card-meta';
        
        const rating = document.createElement('span');
        rating.className = 'image-card-rating';
        rating.textContent = '⭐'.repeat(img.rating || 0);
        meta.appendChild(rating);
        
        const score = document.createElement('span');
        score.textContent = img.score ? `${img.score.toFixed(1)}分` : '';
        meta.appendChild(score);
        
        info.appendChild(meta);
        card.appendChild(info);
      }
      
      // 事件监听
      card.addEventListener('click', (e) => handleCardClick(index, e));
      card.addEventListener('dblclick', () => handleCardDoubleClick(index));
      card.addEventListener('contextmenu', (e) => handleCardContextMenu(index, e));
      
      return card;
    }
    
    // ========== 加载缩略图 ==========
    async function loadThumbnails() {
      const thumbs = document.querySelectorAll('.image-card-thumb');
      
      for (const thumb of thumbs) {
        const path = thumb.dataset.path;
        if (!path) continue;
        
        try {
          const response = await callBridge('getThumbnail', path);
          thumb.src = response.thumbnail;
        } catch (error) {
          console.error('加载缩略图失败:', path, error);
          thumb.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg"/>';
        }
      }
    }
    
    // ========== 事件处理 ==========
    function handleCardClick(index, event) {
      if (event.ctrlKey || event.metaKey) {
        // Ctrl/Cmd + 点击：切换选择
        toggleSelection(index);
      } else if (event.shiftKey) {
        // Shift + 点击：范围选择
        rangeSelect(index);
      } else {
        // 单击：单选
        selectSingle(index);
      }
      
      updateCardSelection();
      updateStatus();
    }
    
    function handleCardDoubleClick(index) {
      console.log('双击图片:', index);
      callBridge('openImage', images[index].file_path);
    }
    
    function handleCardContextMenu(index, event) {
      event.preventDefault();
      console.log('右键菜单:', index);
      // TODO: 显示右键菜单
    }
    
    // ========== 选择逻辑 ==========
    function toggleSelection(index) {
      if (selectedIndices.has(index)) {
        selectedIndices.delete(index);
      } else {
        selectedIndices.add(index);
      }
    }
    
    function selectSingle(index) {
      selectedIndices.clear();
      selectedIndices.add(index);
    }
    
    function rangeSelect(index) {
      const indices = Array.from(selectedIndices);
      if (indices.length === 0) {
        selectedIndices.add(index);
        return;
      }
      
      const lastIndex = Math.max(...indices);
      const start = Math.min(lastIndex, index);
      const end = Math.max(lastIndex, index);
      
      for (let i = start; i <= end; i++) {
        selectedIndices.add(i);
      }
    }
    
    function selectAll() {
      selectedIndices.clear();
      for (let i = 0; i < images.length; i++) {
        selectedIndices.add(i);
      }
      updateCardSelection();
      updateStatus();
    }
    
    function clearSelection() {
      selectedIndices.clear();
      updateCardSelection();
      updateStatus();
    }
    
    function updateCardSelection() {
      const cards = document.querySelectorAll('.image-card');
      cards.forEach((card, index) => {
        if (selectedIndices.has(index)) {
          card.classList.add('selected');
        } else {
          card.classList.remove('selected');
        }
      });
    }
    
    // ========== 工具栏操作 ==========
    function refreshImages() {
      loadImages();
    }
    
    function toggleViewMode() {
      showInfo = !showInfo;
      document.getElementById('viewModeText').textContent = showInfo ? '显示信息' : '隐藏信息';
      renderImages();
    }
    
    // ========== 缩略图大小滑块 ==========
    (function initSizeSlider() {
      const slider = document.getElementById('sizeSlider');
      const fill = document.getElementById('sizeSliderFill');
      const thumb = document.getElementById('sizeSliderThumb');
      const valueLabel = document.getElementById('sizeValue');
      
      const minSize = 120;
      const maxSize = 300;
      let isDragging = false;
      
      function updateSlider(value) {
        const percent = (value - minSize) / (maxSize - minSize) * 100;
        fill.style.width = percent + '%';
        valueLabel.textContent = value + 'px';
        thumbnailSize = value;
      }
      
      function handleMove(clientX) {
        const rect = slider.getBoundingClientRect();
        const percent = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
        const value = Math.round(minSize + percent * (maxSize - minSize));
        updateSlider(value);
      }
      
      thumb.addEventListener('mousedown', (e) => {
        isDragging = true;
        e.preventDefault();
      });
      
      document.addEventListener('mousemove', (e) => {
        if (isDragging) {
          handleMove(e.clientX);
        }
      });
      
      document.addEventListener('mouseup', () => {
        if (isDragging) {
          isDragging = false;
          renderImages();
        }
      });
      
      slider.addEventListener('click', (e) => {
        if (e.target !== thumb) {
          handleMove(e.clientX);
          renderImages();
        }
      });
      
      updateSlider(thumbnailSize);
    })();
    
    // ========== 辅助函数 ==========
    function showLoading() {
      document.getElementById('loading').style.display = 'flex';
      document.getElementById('imageGrid').style.display = 'none';
      document.getElementById('emptyState').style.display = 'none';
    }
    
    function showEmpty() {
      document.getElementById('loading').style.display = 'none';
      document.getElementById('imageGrid').style.display = 'none';
      document.getElementById('emptyState').style.display = 'flex';
    }
    
    function updateStatus() {
      document.getElementById('statusTotal').textContent = `总数: ${images.length}`;
      document.getElementById('statusSelected').textContent = `已选择: ${selectedIndices.size}`;
      document.getElementById('statusLoaded').textContent = `已加载: ${images.length}`;
    }
    
    function getLabelColor(label) {
      const colors = {
        'Red': '#ef4444',
        'Green': '#10b981',
        'Blue': '#3b82f6',
        'Yellow': '#f59e0b',
        'Purple': '#a855f7',
        'Orange': '#f97316',
        'Pink': '#ec4899',
        'White': '#f3f4f6',
        'Black': '#1f2937'
      };
      return colors[label] || '#6b7280';
    }
    
    // ========== Bridge 调用封装 ==========
    function callBridge(method, ...args) {
      return new Promise((resolve, reject) => {
        if (!bridge) {
          reject('Bridge 未连接');
          return;
        }
        
        try {
          bridge[method](...args, function(result) {
            try {
              const data = JSON.parse(result);
              if (data.ok) {
                resolve(data.data);
              } else {
                reject(data.error || '未知错误');
              }
            } catch (e) {
              reject('解析响应失败: ' + e);
            }
          });
        } catch (e) {
          reject('调用失败: ' + e);
        }
      });
    }
  </script>
</body>
</html>
    """


