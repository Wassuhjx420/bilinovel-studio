// 哔哩轻小说 Studio 客户端 - 核心交互与状态机 (Apple Fluid Pro Edition)

const { createApp, ref, reactive, computed, onMounted, nextTick, watch } = Vue;

const app = createApp({
  setup() {
    // 1. 全局主题与状态
    const activeTab = ref('hub'); // 'hub' | 'queue' | 'settings'
    const theme = ref(localStorage.getItem('bilinovel_theme_v2') || 'light');
    const toast = reactive({ show: false, message: '', type: 'info' });
    let toastTimer = null;

    const showToast = (message, type = 'info') => {
      toast.message = message;
      toast.type = type;
      toast.show = true;
      if (toastTimer) clearTimeout(toastTimer);
      toastTimer = setTimeout(() => { toast.show = false; }, 3200);
    };

    const toggleTheme = () => {
      theme.value = theme.value === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', theme.value);
      document.documentElement.classList.toggle('dark', theme.value === 'dark');
      localStorage.setItem('bilinovel_theme_v2', theme.value);
    };

    // ==================== 后端同构 API 桥接层 ====================
    const callApi = async (method, endpoint, payload = {}) => {
      // 1. 如果处于 PyWebView 容器且注入了 API
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api[method] === 'function') {
        try {
          if (Object.keys(payload).length === 0) {
            return await window.pywebview.api[method]();
          } else if (Object.keys(payload).length === 1) {
            return await window.pywebview.api[method](Object.values(payload)[0]);
          } else {
            return await window.pywebview.api[method](payload);
          }
        } catch (e) {
          console.warn(`[PyWebView API] 调用 ${method} 异常:`, e);
        }
      }

      // 2. 否则通过本地 HTTP REST 接口交互
      try {
        const isGet = endpoint.startsWith('GET:');
        const cleanUrl = endpoint.replace(/^(GET|POST):/, '');
        
        let response;
        if (isGet) {
          const params = new URLSearchParams(payload).toString();
          const fullUrl = params ? `${cleanUrl}?${params}` : cleanUrl;
          response = await fetch(fullUrl);
        } else {
          response = await fetch(cleanUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
        }
        return await response.json();
      } catch (err) {
        console.warn(`[REST Bridge] 请求 ${endpoint} 失败:`, err);
        return null;
      }
    };

    // ==================== 2. 工作台与小说解析 (Hub) ====================
    const hub = reactive({
      inputUrl: '',
      isParsing: false,
      book: null,
    });

    const parseNovel = async (customId = null) => {
      let targetInput = customId ? `https://www.linovelib.com/novel/${customId}.html` : hub.inputUrl;
      if (!targetInput || !targetInput.trim()) {
        showToast('请输入轻小说链接或数字 ID', 'warn');
        return;
      }

      targetInput = targetInput.trim();
      hub.inputUrl = targetInput;
      hub.isParsing = true;

      addLog('info', 'PARSER', `开始请求解析小说: ${targetInput}`);

      // 调用后端解析接口
      const res = await callApi('parse_novel', 'POST:/api/parse', { url: targetInput });
      hub.isParsing = false;

      if (res && (res.volumes || (res.book && res.book.volumes))) {
        const bookData = res.book || res;
        if (bookData.volumes) {
          const hasPreSelected = bookData.volumes.some(v => v.selected);
          if (!hasPreSelected) {
            bookData.volumes.forEach(v => v.selected = false);
          }
        }
        hub.book = bookData;
        showToast(`已成功解析：《${bookData.title}》，共 ${bookData.volumes.length} 卷`, 'success');
        addLog('success', 'PARSER', `解析完成: 《${bookData.title}》 [${bookData.volumes.length} 卷]`);
      } else {
        showToast('未能获取到小说数据，请检查链接或网络', 'warn');
      }
    };


    const selectedVolumeCount = computed(() => {
      if (!hub.book || !hub.book.volumes) return 0;
      return hub.book.volumes.filter(v => v.selected).length;
    });

    const selectAllVolumes = () => {
      if (!hub.book) return;
      hub.book.volumes.forEach(v => v.selected = true);
    };

    const invertVolumeSelect = () => {
      if (!hub.book) return;
      hub.book.volumes.forEach(v => v.selected = !v.selected);
    };

    const clearVolumeSelect = () => {
      if (!hub.book) return;
      hub.book.volumes.forEach(v => v.selected = false);
    };

    // ==================== 3. 任务队列与并发监控 (Queue & Monitor) ====================
    const queue = reactive({
      isRunning: false,
      filter: 'all',
      items: []
    });


    const workers = reactive([
      { id: 1, name: 'Worker Tab 1', status: 'idle', task: '就绪 / 空闲' },
      { id: 2, name: 'Worker Tab 2', status: 'idle', task: '就绪 / 空闲' },
      { id: 3, name: 'Worker Tab 3', status: 'idle', task: '就绪 / 空闲' }
    ]);

    const terminal = reactive({
      collapsed: false,
      filter: 'all',
      logs: [
        { id: 1, time: '20:30:01', type: 'info', tag: 'ENGINE', msg: '轻小说爬虫引擎与 Playwright 自动化环境已就绪' },
        { id: 2, time: '20:30:02', type: 'info', tag: 'BRIDGE', msg: '前后端同构服务通道已连接 [PyWebView / REST Active]' },
        { id: 3, time: '20:30:03', type: 'success', tag: 'SYSTEM', msg: 'macOS Sequoia & iOS 18 Fluid UI 系统已就绪' }
      ]
    });

    const addLog = (type, tag, msg) => {
      terminal.logs.push({
        id: Date.now() + Math.random(),
        time: new Date().toTimeString().slice(0, 8),
        type,
        tag,
        msg
      });
      if (terminal.logs.length > 500) terminal.logs.shift();
      nextTick(() => {
        const el = document.getElementById('terminal-log-container');
        if (el) el.scrollTop = el.scrollHeight;
      });
    };

    const clearLogs = () => {
      terminal.logs = [];
      showToast('控制台日志已清屏', 'info');
    };

    const copyLogs = () => {
      const text = terminal.logs.map(l => `[${l.time}] [${l.tag || l.type}] ${l.msg}`).join('\n');
      navigator.clipboard.writeText(text).then(() => {
        showToast('日志已复制到剪贴板', 'success');
      });
    };

    const filteredLogs = computed(() => {
      if (terminal.filter === 'all') return terminal.logs;
      return terminal.logs.filter(l => l.type === terminal.filter);
    });

    const addSelectedToQueue = (startNow = false) => {
      if (!hub.book) return;
      const selectedVols = hub.book.volumes.filter(v => v.selected);
      if (selectedVols.length === 0) {
        showToast('请先勾选需要下载的分卷', 'warn');
        return;
      }

      selectedVols.forEach(vol => {
        const exists = queue.items.find(i => i.novelId === hub.book.novel_id && i.volumeTitle === vol.title);
        if (!exists) {
          queue.items.push({
            id: `task_${Date.now()}_${Math.floor(Math.random()*1000)}`,
            novelId: hub.book.novel_id,
            novelTitle: hub.book.title,
            volumeTitle: vol.title,
            cover: vol.cover || hub.book.cover,
            totalChapters: vol.chapterCount || (vol.chapters ? vol.chapters.length : 20),
            chapters: vol.chapters || [],
            completedChapters: 0,
            status: 'pending',
            progress: 0,
            speed: '0 KB/s',
            eta: '--:--',
            elapsed: '00:00',
          });

        }
      });

      showToast(`已将 ${selectedVols.length} 卷加入下载队列`, 'success');
      addLog('info', 'QUEUE', `已将 ${selectedVols.length} 个分卷任务加入队列`);
      activeTab.value = 'queue';

      if (startNow) {
        startQueue();
      }
    };

    const moveTaskUp = (index) => {
      if (index > 0) {
        const item = queue.items.splice(index, 1)[0];
        queue.items.splice(index - 1, 0, item);
      }
    };

    const moveTaskDown = (index) => {
      if (index < queue.items.length - 1) {
        const item = queue.items.splice(index, 1)[0];
        queue.items.splice(index + 1, 0, item);
      }
    };

    const removeTask = (taskId) => {
      const idx = queue.items.findIndex(i => i.id === taskId);
      if (idx !== -1) {
        const item = queue.items.splice(idx, 1)[0];
        showToast(`已移除任务: 《${item.novelTitle}》 ${item.volumeTitle}`, 'info');
      }
    };

    const retryTask = (task) => {
      task.status = 'pending';
      task.progress = 0;
      task.completedChapters = 0;
      showToast(`已重置任务: 《${task.novelTitle}》 ${task.volumeTitle}`, 'info');
      startQueue();
    };

    const clearCompleted = () => {
      queue.items = queue.items.filter(i => i.status !== 'completed');
      showToast('已清空所有已完成任务', 'info');
    };

    const filteredQueueItems = computed(() => {
      if (queue.filter === 'all') return queue.items;
      return queue.items.filter(i => i.status === queue.filter);
    });

    const activeDownloadingTask = computed(() => {
      return queue.items.find(i => i.status === 'downloading') || null;
    });

    // 真实后端下载队列调度
    const startQueue = async () => {
      const pendingTasks = queue.items.filter(i => i.status === 'pending' || i.status === 'downloading');
      if (pendingTasks.length === 0) {
        showToast('队列中没有待下载的任务', 'info');
        return;
      }

      queue.isRunning = true;
      if (pendingTasks[0] && pendingTasks[0].status === 'pending') {
        pendingTasks[0].status = 'downloading';
      }
      showToast('下载队列流水线已启动', 'success');
      addLog('info', 'QUEUE', `向后端提交 ${pendingTasks.length} 个分卷下载任务`);

      // 调用后端启动接口
      await callApi('start_download', 'POST:/api/download/start', {
        tasks: JSON.parse(JSON.stringify(pendingTasks)),
        settings: {
          downloadDir: settings.downloadDir,
          concurrencyTabs: settings.concurrencyTabs,
          headless: settings.headless,
          autoOpenFolder: settings.autoOpenFolder,
          calibreMeta: true,
          kavitaMeta: true,
          dedupImages: true,
          japaneseLayout: true
        }
      });
    };


    const pauseQueue = async () => {
      queue.isRunning = false;
      showToast('下载队列已暂停', 'warn');
      addLog('warn', 'QUEUE', '暂停后台下载工作流');
      await callApi('pause_download', 'POST:/api/download/pause');
    };

    // ==================== 4. 偏好设置中心 (Settings) ====================
    const fontPresets = {
      system: '-apple-system, BlinkMacSystemFont, "Segoe UI Variable Text", "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif',
      yahei: '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif',
      segoe: '"Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI", sans-serif',
      pingfang: '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei UI", -apple-system, sans-serif',
      noto_sans: '"Noto Sans SC", "Source Han Sans SC", "Microsoft YaHei UI", sans-serif',
      noto_serif: '"Noto Serif SC", "Source Han Serif SC", "Songti SC", SimSun, serif',
      lxgw: '"LXGW WenKai", "Kaiti SC", KaiTi, serif',
      custom: ''
    };

    let backendDefaultDir = '';

    const settings = reactive({
      downloadDir: '',
      autoOpenFolder: true,
      autoOpenEpub: false,
      cleanupTemp: true,
      concurrencyTabs: 3,
      headless: true,
      maxRetries: 3,

      randomDelay: 0.5,
      calibreMeta: true,
      kavitaMeta: true,
      dedupImages: true,
      japaneseLayout: true,
      themeMode: 'light',
      fontPreset: 'system',
      customFont: '',
      _headlessDefaultV2: true,
    });

    const applyTypography = () => {
      let fontFam = fontPresets[settings.fontPreset] || fontPresets.system;
      if (settings.fontPreset === 'custom' && settings.customFont && settings.customFont.trim()) {
        fontFam = `"${settings.customFont.trim()}", ${fontPresets.system}`;
      }
      document.documentElement.style.setProperty('--app-font-family', fontFam);
      document.documentElement.style.fontSize = '18.2px';
    };

    watch([() => settings.fontPreset, () => settings.customFont], () => {
      applyTypography();
    });

    const syncDefaultSettings = async () => {
      try {
        const res = await callApi('get_defaults', 'GET:/api/defaults');
        if (res && res.downloadDir) {
          backendDefaultDir = res.downloadDir;
          if (!settings.downloadDir) {
            settings.downloadDir = res.downloadDir;
            localStorage.setItem('bilinovel_settings', JSON.stringify(settings));
          }
        }
      } catch (e) {}
    };

    const loadSettings = () => {
      const saved = localStorage.getItem('bilinovel_settings');
      if (saved) {
        try {
          const parsed = JSON.parse(saved);
          Object.assign(settings, parsed);
          // 若为旧版本配置且未迁移过无头默认值，自动将其设置为默认开启
          if (parsed._headlessDefaultV2 !== true) {
            settings.headless = true;
            settings._headlessDefaultV2 = true;
            localStorage.setItem('bilinovel_settings', JSON.stringify(settings));
          }
        } catch (e) {}
      } else {
        settings.headless = true;
        settings._headlessDefaultV2 = true;
      }
      applyTypography();
      syncDefaultSettings();
    };

    const saveSettings = () => {
      settings._headlessDefaultV2 = true;
      localStorage.setItem('bilinovel_settings', JSON.stringify(settings));
      applyTypography();
      showToast('偏好与字体设置已成功保存', 'success');
      addLog('info', 'CONFIG', `系统偏好已更新 [字体: ${settings.fontPreset} / 无头模式: ${settings.headless ? '开启' : '关闭'}]`);
    };

    const resetSettings = () => {
      localStorage.removeItem('bilinovel_settings');
      settings.downloadDir = backendDefaultDir || '';
      settings.concurrencyTabs = 3;
      settings.headless = true;
      settings.maxRetries = 3;
      settings.randomDelay = 0.5;
      settings.calibreMeta = true;
      settings.kavitaMeta = true;
      settings.dedupImages = true;
      settings.japaneseLayout = true;
      settings.fontPreset = 'system';
      settings.customFont = '';
      applyTypography();
      showToast('已恢复默认配置与标准字体', 'info');
    };

    const chooseFolder = async () => {
      const res = await callApi('choose_folder', 'GET:/api/choose_folder');
      if (res && res.folder) {
        settings.downloadDir = res.folder;
        showToast(`已选择目录: ${res.folder}`, 'success');
      } else if (typeof res === 'string') {
        settings.downloadDir = res;
        showToast(`已选择目录: ${res}`, 'success');
      }
    };

    // ==================== 6. 全局事件总线处理 ====================
    const handleBackendEvent = (type, data) => {
      if (type === 'log') {
        addLog(data.level || 'info', data.tag || 'SYSTEM', data.msg);
      } else if (type === 'progress') {
        const task = queue.items.find(i => i.id === data.taskId || (i.novelTitle === data.novelTitle && i.volumeTitle === data.volumeTitle));
        if (task) {
          task.status = 'downloading';
          task.progress = data.progress;
          task.completedChapters = data.completed;
          task.totalChapters = data.total;
          task.speed = data.speed;
          task.elapsed = data.elapsed;
          task.eta = data.eta;
        }
      } else if (type === 'worker_status') {
        const w = workers.find(w => w.id === data.workerId);
        if (w) {
          w.status = data.status;
          w.task = data.task;
        }
      } else if (type === 'task_started') {
        const task = queue.items.find(i => i.id === data.taskId);
        if (task) task.status = 'downloading';
      } else if (type === 'task_completed') {
        const task = queue.items.find(i => i.id === data.taskId);
        if (task) {
          task.status = 'completed';
          task.progress = 100;
        }
      }
    };

    // 挂载全局监听器
    window.__onBackendEvent = (type, data) => {
      handleBackendEvent(type, data);
    };

    // 浏览器环境下的长轮询事件推流循环
    const startEventPolling = async () => {
      while (true) {
        try {
          const res = await fetch('/api/events');
          if (res.ok) {
            const data = await res.json();
            if (data && Array.isArray(data.events)) {
              data.events.forEach(ev => handleBackendEvent(ev.type, ev.data));
            }
          }
        } catch (e) {
          await new Promise(r => setTimeout(r, 2000));
        }
      }
    };

    // 初始化
    onMounted(() => {
      document.documentElement.setAttribute('data-theme', theme.value);
      document.documentElement.classList.toggle('dark', theme.value === 'dark');
      loadSettings();
      startEventPolling();
    });


    return {
      activeTab,
      theme,
      toast,
      showToast,
      toggleTheme,
      // Hub
      hub,
      parseNovel,
      selectedVolumeCount,
      selectAllVolumes,
      invertVolumeSelect,
      clearVolumeSelect,
      // Queue & Monitor
      queue,
      workers,
      terminal,
      addLog,
      clearLogs,
      copyLogs,
      filteredLogs,
      addSelectedToQueue,
      startQueue,
      pauseQueue,
      retryTask,
      removeTask,
      moveTaskUp,
      moveTaskDown,
      clearCompleted,
      filteredQueueItems,
      activeDownloadingTask,
      // Settings
      settings,
      saveSettings,
      resetSettings,
      chooseFolder,
      applyTypography
    };
  }
});

app.mount('#app');
