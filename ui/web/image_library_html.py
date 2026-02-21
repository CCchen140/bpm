"""
图库HTML生成器
生成完整的Web版图库界面
"""
from ui.web.web_style_manager import get_style_manager


def build_image_library_html() -> str:
    """
    构建图库HTML
    
    Returns:
        完整的HTML字符串
    """
    style_manager = get_style_manager()
    styles = style_manager.get_all_styles()
    
    html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>图库 Web 版</title>
    <style>
        {styles}
    </style>
</head>
<body>
    <div class="container">
        <!-- 左侧文件树 -->
        <div class="sidebar">
            <div class="tree-header">
                <span>物种分类</span>
            </div>
            <div class="tree-container" id="treeContainer">
                <div style="padding: 20px; text-align: center; color: #858585;">
                    加载中...
                </div>
            </div>
        </div>
        
        <!-- 中间内容区 -->
        <div class="main-content">
            <div class="toolbar">
                <!-- 文件操作 -->
                <button class="btn-icon" id="btnRefresh" data-tooltip="刷新">
                    <svg class="icon" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M42 8V24" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
                        <path d="M6 24L6 40" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
                        <path d="M42 24C42 14.0589 33.9411 6 24 6C18.9145 6 14.3216 8.10896 11.0481 11.5M6 24C6 33.9411 14.0589 42 24 42C28.8556 42 33.2622 40.0774 36.5 36.9519" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                </button>
                
                <div class="toolbar-separator"></div>
                
                <!-- 快速筛选 -->
                <button class="btn-icon" id="btnFavorite" data-tooltip="收藏">
                    <svg class="icon" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M15 8C8.925 8 4 12.925 4 19C4 30 17 40 24 42.326C31 40 44 30 44 19C44 12.925 39.075 8 33 8C29.28 8 25.99 9.847 24 12.674C22.01 9.847 18.72 8 15 8Z" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                </button>
                
                <button class="btn-icon" id="btnRating" data-tooltip="评分筛选">
                    <svg class="icon" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M23.9986 5L17.8856 17.4776L4 19.4911L14.0589 29.3251L11.6544 43L23.9986 36.4192L36.3454 43L33.9586 29.3251L44 19.4911L30.1913 17.4776L23.9986 5Z" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                </button>
                
                <button class="btn-icon" id="btnFilter" data-tooltip="高级筛选">
                    <svg class="icon" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M6 9L20.4 25.8178V38.4444L27.6 42V25.8178L42 9H6Z" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                </button>
                
                <div class="toolbar-separator"></div>
                
                <!-- 视图切换 -->
                <button class="btn-icon active" id="btnViewGrid" data-tooltip="网格视图">
                    <svg class="icon" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <rect x="6" y="6" width="16" height="16" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
                        <rect x="26" y="6" width="16" height="16" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
                        <rect x="6" y="26" width="16" height="16" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
                        <rect x="26" y="26" width="16" height="16" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                </button>
                
                <button class="btn-icon" id="btnViewList" data-tooltip="列表视图">
                    <svg class="icon" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M9 10H39" stroke="currentColor" stroke-width="4" stroke-linecap="round"/>
                        <path d="M9 19H39" stroke="currentColor" stroke-width="4" stroke-linecap="round"/>
                        <path d="M9 28H39" stroke="currentColor" stroke-width="4" stroke-linecap="round"/>
                        <path d="M9 37H39" stroke="currentColor" stroke-width="4" stroke-linecap="round"/>
                    </svg>
                </button>
                
                <div class="toolbar-separator"></div>
                
                <!-- 排序 -->
                <select class="toolbar-select" id="sortSelect">
                    <option value="name_asc">名称 ↑</option>
                    <option value="name_desc">名称 ↓</option>
                    <option value="date_asc">日期 ↑</option>
                    <option value="date_desc">日期 ↓</option>
                    <option value="rating_desc">评分 ↓</option>
                    <option value="size_desc">大小 ↓</option>
                </select>
                
                <div style="flex: 1;"></div>
                
                <!-- 缩略图大小 -->
                <span style="font-size: 12px; color: #858585; margin-right: 8px;">缩略图大小</span>
                <input type="range" id="thumbnailSize" min="100" max="300" value="180" step="20" style="width: 120px;">
                
                <div class="toolbar-separator"></div>
                
                <span id="imageCount" style="font-size: 13px; color: #858585;">0 张图片</span>
            </div>
            <div class="content-area">
                <div class="grid-container" id="gridContainer">
                    <div style="grid-column: 1 / -1; padding: 40px; text-align: center; color: #858585;">
                        请从左侧选择一个分类
                    </div>
                </div>
            </div>
        </div>
        
        <!-- 右侧预览和信息面板 -->
        <div class="right-panel">
            <!-- 预览面板 -->
            <div class="preview-container" id="previewContainer">
                <div class="preview-empty">未选择图片</div>
            </div>
            
            <!-- 信息面板 -->
            <div style="flex: 1; display: flex; flex-direction: column; overflow: hidden;">
                <div class="info-header">
                    <span>图片信息</span>
                </div>
                <div class="info-content" id="infoContent">
                    <div style="padding: 20px; text-align: center; color: #858585;">
                        未选择图片
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <script>
        // 全局变量
        let bridge = null;
        let currentFolder = null;
        let currentImage = null;
        let selectedImageId = null;
        let currentImages = [];
        let thumbnailSize = 180;
        let viewMode = 'grid'; // 'grid' or 'list'
        let filterFavorite = false;
        let filterRating = 0;
        
        // 初始化WebChannel
        new QWebChannel(qt.webChannelTransport, function(channel) {{
            bridge = channel.objects.bridge;
            console.log('WebChannel 已连接');
            
            // 监听后端信号
            bridge.treeUpdated.connect(onTreeUpdated);
            bridge.imagesUpdated.connect(onImagesUpdated);
            bridge.imageDetailUpdated.connect(onImageDetailUpdated);
            
            // 加载文件树
            loadFolderTree();
        }});
        
        // 加载文件树
        function loadFolderTree() {{
            if (!bridge) return;
            
            bridge.getFolderTree(function(jsonStr) {{
                try {{
                    const treeData = JSON.parse(jsonStr);
                    renderTree(treeData);
                }} catch (e) {{
                    console.error('解析文件树失败:', e);
                    bridge.logError('解析文件树失败: ' + e.message);
                }}
            }});
        }}
        
        // 渲染文件树
        function renderTree(treeData) {{
            const container = document.getElementById('treeContainer');
            container.innerHTML = '';
            
            if (!treeData || treeData.length === 0) {{
                container.innerHTML = '<div style="padding: 20px; text-align: center; color: #858585;">暂无数据</div>';
                return;
            }}
            
            treeData.forEach(node => {{
                renderTreeNode(node, container, 0);
            }});
        }}
        
        // 渲染树节点
        function renderTreeNode(node, container, level) {{
            const nodeDiv = document.createElement('div');
            nodeDiv.className = 'tree-node';
            nodeDiv.style.paddingLeft = (level * 16 + 8) + 'px';
            nodeDiv.dataset.id = node.id;
            
            // 图标
            const icon = document.createElement('span');
            icon.className = 'tree-node-icon';
            icon.textContent = node.children && node.children.length > 0 ? '📁' : '📄';
            nodeDiv.appendChild(icon);
            
            // 标签
            const label = document.createElement('span');
            label.className = 'tree-node-label';
            label.textContent = node.label;
            nodeDiv.appendChild(label);
            
            // 数量
            if (node.count !== undefined) {{
                const count = document.createElement('span');
                count.className = 'tree-node-count';
                count.textContent = '(' + node.count + ')';
                nodeDiv.appendChild(count);
            }}
            
            // 点击事件
            nodeDiv.addEventListener('click', function(e) {{
                e.stopPropagation();
                selectFolder(node.id);
                
                // 更新选中状态
                document.querySelectorAll('.tree-node').forEach(n => n.classList.remove('selected'));
                nodeDiv.classList.add('selected');
            }});
            
            container.appendChild(nodeDiv);
            
            // 递归渲染子节点
            if (node.children && node.children.length > 0) {{
                node.children.forEach(child => {{
                    renderTreeNode(child, container, level + 1);
                }});
            }}
        }}
        
        // 选择文件夹
        function selectFolder(folderId) {{
            if (!bridge) return;
            
            currentFolder = folderId;
            selectedImageId = null;
            
            // 清空预览
            clearPreview();
            
            // 加载图片列表
            bridge.getImagesByFolder(folderId, function(jsonStr) {{
                try {{
                    const images = JSON.parse(jsonStr);
                    renderImages(images);
                }} catch (e) {{
                    console.error('解析图片列表失败:', e);
                    bridge.logError('解析图片列表失败: ' + e.message);
                }}
            }});
        }}
        
        // 渲染图片网格
        function renderImages(images) {{
            const container = document.getElementById('gridContainer');
            const countEl = document.getElementById('imageCount');
            
            // 保存当前图片列表
            if (images !== currentImages) {{
                currentImages = images;
            }}
            
            container.innerHTML = '';
            countEl.textContent = images.length + ' 张图片';
            
            if (!images || images.length === 0) {{
                container.innerHTML = '<div style="grid-column: 1 / -1; padding: 40px; text-align: center; color: #858585;">该分类下暂无图片</div>';
                return;
            }}
            
            // 根据视图模式渲染
            if (viewMode === 'list') {{
                container.style.display = 'flex';
                container.style.flexDirection = 'column';
                container.style.gap = '1px';
            }} else {{
                container.style.display = 'grid';
                container.style.flexDirection = '';
                container.style.gap = '12px';
            }}
            
            images.forEach(image => {{
                const item = document.createElement('div');
                item.className = viewMode === 'grid' ? 'grid-item' : 'list-item';
                item.dataset.id = image.id;
                
                if (viewMode === 'grid') {{
                    item.style.width = thumbnailSize + 'px';
                    item.style.height = thumbnailSize + 'px';
                }}
                
                // 图片
                const img = document.createElement('img');
                img.className = viewMode === 'grid' ? 'grid-item-image' : 'list-item-image';
                img.src = image.thumbnail || '';
                img.alt = image.name;
                item.appendChild(img);
                
                // 信息
                const info = document.createElement('div');
                info.className = viewMode === 'grid' ? 'grid-item-info' : 'list-item-info';
                
                const name = document.createElement('div');
                name.className = viewMode === 'grid' ? 'grid-item-name' : 'list-item-name';
                name.textContent = image.name;
                name.title = image.name;
                info.appendChild(name);
                
                const meta = document.createElement('div');
                meta.className = viewMode === 'grid' ? 'grid-item-meta' : 'list-item-meta';
                meta.textContent = image.species || '';
                info.appendChild(meta);
                
                // 添加评分和收藏标记
                if (image.rating > 0 || image.favorite) {{
                    const badges = document.createElement('div');
                    badges.style.cssText = 'display: flex; gap: 4px; margin-top: 4px;';
                    
                    if (image.favorite) {{
                        const favBadge = document.createElement('span');
                        favBadge.textContent = '❤️';
                        favBadge.style.fontSize = '12px';
                        badges.appendChild(favBadge);
                    }}
                    
                    if (image.rating > 0) {{
                        const ratingBadge = document.createElement('span');
                        ratingBadge.textContent = '⭐'.repeat(image.rating);
                        ratingBadge.style.fontSize = '10px';
                        badges.appendChild(ratingBadge);
                    }}
                    
                    info.appendChild(badges);
                }}
                
                item.appendChild(info);
                
                // 点击事件
                item.addEventListener('click', function() {{
                    selectImage(image.id);
                    
                    // 更新选中状态
                    const selector = viewMode === 'grid' ? '.grid-item' : '.list-item';
                    document.querySelectorAll(selector).forEach(i => i.classList.remove('selected'));
                    item.classList.add('selected');
                }});
                
                container.appendChild(item);
            }});
        }}
        
        // 选择图片
        function selectImage(imageId) {{
            if (!bridge) return;
            
            selectedImageId = imageId;
            
            // 加载图片详情
            bridge.getImageDetail(imageId, function(jsonStr) {{
                try {{
                    const detail = JSON.parse(jsonStr);
                    if (detail && detail.id) {{
                        currentImage = detail;
                        renderPreview(detail);
                        renderInfo(detail);
                    }}
                }} catch (e) {{
                    console.error('解析图片详情失败:', e);
                    bridge.logError('解析图片详情失败: ' + e.message);
                }}
            }});
        }}
        
        // 渲染预览
        function renderPreview(detail) {{
            const container = document.getElementById('previewContainer');
            container.innerHTML = '';
            
            if (!detail.preview) {{
                container.innerHTML = '<div class="preview-empty">无法加载预览</div>';
                return;
            }}
            
            const img = document.createElement('img');
            img.className = 'preview-image';
            img.src = detail.preview;
            img.alt = detail.name;
            container.appendChild(img);
        }}
        
        // 渲染信息
        function renderInfo(detail) {{
            const container = document.getElementById('infoContent');
            container.innerHTML = '';
            
            // 基本信息
            const basicSection = createInfoSection('基本信息', [
                {{ label: '文件名', value: detail.name }},
                {{ label: '尺寸', value: detail.width + ' × ' + detail.height }},
                {{ label: '大小', value: formatFileSize(detail.size) }},
                {{ label: '拍摄时间', value: detail.date || '未知' }},
            ]);
            container.appendChild(basicSection);
            
            // 物种信息
            const speciesSection = createInfoSection('物种信息', [
                {{ label: '目', value: detail.order || '未知' }},
                {{ label: '科', value: detail.family || '未知' }},
                {{ label: '属', value: detail.genus || '未知' }},
                {{ label: '种', value: detail.species || '未知' }},
            ]);
            container.appendChild(speciesSection);
            
            // 拍摄参数
            if (detail.camera || detail.lens) {{
                const cameraSection = createInfoSection('拍摄参数', [
                    {{ label: '相机', value: detail.camera || '未知' }},
                    {{ label: '镜头', value: detail.lens || '未知' }},
                    {{ label: 'ISO', value: detail.iso || '未知' }},
                    {{ label: '光圈', value: detail.aperture || '未知' }},
                    {{ label: '快门', value: detail.shutter || '未知' }},
                    {{ label: '焦距', value: detail.focal_length || '未知' }},
                ]);
                container.appendChild(cameraSection);
            }}
            
            // 地理位置
            if (detail.latitude || detail.longitude) {{
                const locationSection = createInfoSection('地理位置', [
                    {{ label: '纬度', value: detail.latitude || '未知' }},
                    {{ label: '经度', value: detail.longitude || '未知' }},
                ]);
                container.appendChild(locationSection);
            }}
        }}
        
        // 创建信息区块
        function createInfoSection(title, rows) {{
            const section = document.createElement('div');
            section.className = 'info-section';
            
            const titleEl = document.createElement('div');
            titleEl.className = 'info-section-title';
            titleEl.textContent = title;
            section.appendChild(titleEl);
            
            rows.forEach(row => {{
                const rowEl = document.createElement('div');
                rowEl.className = 'info-row';
                
                const label = document.createElement('div');
                label.className = 'info-label';
                label.textContent = row.label;
                rowEl.appendChild(label);
                
                const value = document.createElement('div');
                value.className = 'info-value';
                value.textContent = row.value || '-';
                rowEl.appendChild(value);
                
                section.appendChild(rowEl);
            }});
            
            return section;
        }}
        
        // 清空预览
        function clearPreview() {{
            document.getElementById('previewContainer').innerHTML = '<div class="preview-empty">未选择图片</div>';
            document.getElementById('infoContent').innerHTML = '<div style="padding: 20px; text-align: center; color: #858585;">未选择图片</div>';
        }}
        
        // 格式化文件大小
        function formatFileSize(bytes) {{
            if (!bytes) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return (bytes / Math.pow(k, i)).toFixed(2) + ' ' + sizes[i];
        }}
        
        // 后端信号处理
        function onTreeUpdated(jsonStr) {{
            try {{
                const treeData = JSON.parse(jsonStr);
                renderTree(treeData);
            }} catch (e) {{
                console.error('更新文件树失败:', e);
            }}
        }}
        
        function onImagesUpdated(jsonStr) {{
            try {{
                const images = JSON.parse(jsonStr);
                renderImages(images);
            }} catch (e) {{
                console.error('更新图片列表失败:', e);
            }}
        }}
        
        function onImageDetailUpdated(jsonStr) {{
            try {{
                const detail = JSON.parse(jsonStr);
                if (detail && detail.id) {{
                    currentImage = detail;
                    renderPreview(detail);
                    renderInfo(detail);
                }}
            }} catch (e) {{
                console.error('更新图片详情失败:', e);
            }}
        }}
        
        // 刷新按钮
        document.getElementById('btnRefresh').addEventListener('click', function() {{
            if (currentFolder) {{
                selectFolder(currentFolder);
            }} else {{
                loadFolderTree();
            }}
        }});
        
        // 收藏筛选
        document.getElementById('btnFavorite').addEventListener('click', function() {{
            filterFavorite = !filterFavorite;
            this.classList.toggle('active', filterFavorite);
            applyFilters();
        }});
        
        // 评分筛选
        document.getElementById('btnRating').addEventListener('click', function() {{
            // 循环切换评分筛选：0 -> 3 -> 4 -> 5 -> 0
            const ratings = [0, 3, 4, 5];
            const currentIndex = ratings.indexOf(filterRating);
            filterRating = ratings[(currentIndex + 1) % ratings.length];
            this.classList.toggle('active', filterRating > 0);
            if (filterRating > 0) {{
                this.setAttribute('data-tooltip', '评分 ≥ ' + filterRating);
            }} else {{
                this.setAttribute('data-tooltip', '评分筛选');
            }}
            applyFilters();
        }});
        
        // 高级筛选
        document.getElementById('btnFilter').addEventListener('click', function() {{
            alert('高级筛选功能开发中...');
        }});
        
        // 视图切换
        document.getElementById('btnViewGrid').addEventListener('click', function() {{
            viewMode = 'grid';
            document.getElementById('btnViewGrid').classList.add('active');
            document.getElementById('btnViewList').classList.remove('active');
            renderImages(currentImages);
        }});
        
        document.getElementById('btnViewList').addEventListener('click', function() {{
            viewMode = 'list';
            document.getElementById('btnViewList').classList.add('active');
            document.getElementById('btnViewGrid').classList.remove('active');
            renderImages(currentImages);
        }});
        
        // 排序
        document.getElementById('sortSelect').addEventListener('change', function() {{
            sortImages(this.value);
        }});
        
        // 缩略图大小
        document.getElementById('thumbnailSize').addEventListener('input', function() {{
            thumbnailSize = parseInt(this.value);
            updateThumbnailSize();
        }});
        
        // 应用筛选
        function applyFilters() {{
            let filtered = currentImages;
            
            if (filterFavorite) {{
                filtered = filtered.filter(img => img.favorite);
            }}
            
            if (filterRating > 0) {{
                filtered = filtered.filter(img => img.rating >= filterRating);
            }}
            
            renderImages(filtered);
        }}
        
        // 排序图片
        function sortImages(sortType) {{
            const [field, order] = sortType.split('_');
            
            currentImages.sort((a, b) => {{
                let valA = a[field] || '';
                let valB = b[field] || '';
                
                if (field === 'date') {{
                    valA = new Date(valA).getTime() || 0;
                    valB = new Date(valB).getTime() || 0;
                }}
                
                if (order === 'asc') {{
                    return valA > valB ? 1 : -1;
                }} else {{
                    return valA < valB ? 1 : -1;
                }}
            }});
            
            applyFilters();
        }}
        
        // 更新缩略图大小
        function updateThumbnailSize() {{
            const items = document.querySelectorAll('.grid-item');
            items.forEach(item => {{
                item.style.width = thumbnailSize + 'px';
                item.style.height = thumbnailSize + 'px';
            }});
        }}
        
        // 添加测试图片
        function addTestImage() {{
            const testImage = {{
                id: 'test_001',
                path: '/test/bird.jpg',
                name: '测试图片 - 白头鹎.jpg',
                thumbnail: 'data:image/svg+xml;base64,' + btoa(`
                    <svg width="200" height="200" xmlns="http://www.w3.org/2000/svg">
                        <rect width="200" height="200" fill="#e3f2fd"/>
                        <circle cx="100" cy="80" r="30" fill="#1976d2"/>
                        <ellipse cx="100" cy="130" rx="40" ry="50" fill="#1976d2"/>
                        <path d="M 70 130 Q 60 150 70 160" stroke="#1976d2" stroke-width="3" fill="none"/>
                        <path d="M 130 130 Q 140 150 130 160" stroke="#1976d2" stroke-width="3" fill="none"/>
                        <circle cx="90" cy="75" r="5" fill="white"/>
                        <circle cx="110" cy="75" r="5" fill="white"/>
                        <path d="M 95 90 L 100 95 L 105 90" stroke="#ff9800" stroke-width="2" fill="none"/>
                        <text x="100" y="190" text-anchor="middle" font-size="14" fill="#666">测试图片</text>
                    </svg>
                `),
                species: '白头鹎',
                rating: 4,
                favorite: true,
                width: 4000,
                height: 3000,
                size: 5242880,
                date: '2024-02-17 10:30:00',
            }};
            
            currentImages = [testImage];
            renderImages(currentImages);
        }}
        
        // 页面加载完成后添加测试图片
        window.addEventListener('load', function() {{
            setTimeout(addTestImage, 1000);
        }});
    </script>
</body>
</html>
    """
    
    return html

