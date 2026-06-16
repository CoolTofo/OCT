(function(){
    const DEFAULT_LAST_FRAME_OFFSET = 0.08;

    function waitForVideoEvent(video, eventName, timeoutMs=15000){
        return new Promise((resolve, reject) => {
            let timer = null;
            const cleanup = () => {
                if(timer) clearTimeout(timer);
                video.removeEventListener(eventName, onEvent);
                video.removeEventListener('error', onError);
            };
            const onEvent = () => {
                cleanup();
                resolve();
            };
            const onError = () => {
                cleanup();
                reject(new Error('视频无法解码，不能提取帧'));
            };
            timer = setTimeout(() => {
                cleanup();
                reject(new Error('视频加载超时，不能提取帧'));
            }, timeoutMs);
            video.addEventListener(eventName, onEvent, {once:true});
            video.addEventListener('error', onError, {once:true});
        });
    }

    async function ensureMetadata(video){
        if(video.readyState >= 1 && video.videoWidth && video.videoHeight) return;
        await waitForVideoEvent(video, 'loadedmetadata');
    }

    async function seekVideo(video, time){
        const nextTime = Math.max(0, Number(time || 0));
        if(Math.abs(Number(video.currentTime || 0) - nextTime) < 0.015){
            if(video.readyState >= 2) return;
            await waitForVideoEvent(video, 'loadeddata');
            return;
        }
        const seeked = waitForVideoEvent(video, 'seeked');
        video.currentTime = nextTime;
        await seeked;
    }

    async function canvasToBlob(canvas, type='image/png', quality){
        return new Promise(resolve => canvas.toBlob(resolve, type, quality));
    }

    function cleanVideoElement(video){
        try {
            video.removeAttribute('src');
            video.load();
        } catch {}
    }

    async function extractFrameFromUrl(url, options={}){
        if(!url) throw new Error('缺少视频地址');
        const video = document.createElement('video');
        video.muted = true;
        video.playsInline = true;
        video.preload = 'metadata';
        video.crossOrigin = 'anonymous';
        video.src = url;
        try {
            await ensureMetadata(video);
            const fallbackDuration = Number(options.fallbackDuration || 0);
            const duration = Number.isFinite(video.duration) && video.duration > 0 ? video.duration : fallbackDuration;
            const edge = options.edge === 'last' ? 'last' : 'first';
            const targetTime = edge === 'last'
                ? Math.max(0, Number(duration || 0) - DEFAULT_LAST_FRAME_OFFSET)
                : 0;
            await seekVideo(video, targetTime);
            if(video.readyState < 2) await waitForVideoEvent(video, 'loadeddata');
            const width = video.videoWidth;
            const height = video.videoHeight;
            if(!width || !height) throw new Error('视频尺寸读取失败，不能提取帧');
            const canvas = document.createElement('canvas');
            canvas.width = width;
            canvas.height = height;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(video, 0, 0, width, height);
            const blob = await canvasToBlob(canvas, 'image/png');
            if(!blob) throw new Error('视频帧导出失败');
            return {blob, width, height, time:targetTime, duration:Number(duration || 0), edge};
        } catch(err) {
            if(err?.name === 'SecurityError'){
                throw new Error('视频来源不允许浏览器抽帧，请先上传到本地素材后再试');
            }
            throw err;
        } finally {
            cleanVideoElement(video);
        }
    }

    window.CanvasVideoFrame = {
        extractFrameFromUrl,
    };
})();
