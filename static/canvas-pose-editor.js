/*
 * Canvas pose editor helpers.
 *
 * Keeps OpenPose skeleton math and rendering outside the large canvas.html file.
 */
(function initCanvasPoseEditor(global){
    'use strict';

    const WIDTH = 512;
    const HEIGHT = 512;

    const KEYPOINTS = Object.freeze([
        'nose','neck','rightShoulder','rightElbow','rightWrist','leftShoulder','leftElbow','leftWrist',
        'rightHip','rightKnee','rightAnkle','leftHip','leftKnee','leftAnkle','rightEye','leftEye','rightEar','leftEar'
    ]);

    const LIMBS = Object.freeze([
        [1,2,'#ff1f1f'], [2,3,'#ff8a00'], [3,4,'#ffd000'],
        [1,5,'#b7ff00'], [5,6,'#58e000'], [6,7,'#00c853'],
        [1,8,'#00d1ff'], [8,9,'#00a0ff'], [9,10,'#005dff'],
        [1,11,'#ffe600'], [11,12,'#b0d400'], [12,13,'#ff5a00'],
        [1,0,'#2d4bff'], [0,14,'#e000ff'], [14,16,'#d000ff'],
        [0,15,'#ff00b8'], [15,17,'#cc00ff'], [2,5,'#ff0000'], [8,11,'#ffd000']
    ]);

    const DEFAULT_POINTS = Object.freeze([
        [256,92], [256,140], [204,142], [184,214], [164,286], [308,142], [330,214], [350,286],
        [226,286], [214,382], [214,472], [286,286], [300,382], [304,472], [238,72], [274,72], [224,86], [288,86]
    ]);

    function clamp(value, min, max){
        return Math.max(min, Math.min(max, Number(value) || 0));
    }

    function keypointsArrayFromPoints(points){
        return KEYPOINTS.flatMap((_, i) => {
            const point = points[i] || DEFAULT_POINTS[i];
            return [Number(point[0]) || 0, Number(point[1]) || 0, point[2] === 0 ? 0 : 1];
        });
    }

    function defaultPoseData(width=WIDTH, height=HEIGHT){
        return {
            width,
            height,
            people:[{pose_keypoints_2d:keypointsArrayFromPoints(DEFAULT_POINTS)}]
        };
    }

    function normalizePoseData(data, width=WIDTH, height=HEIGHT){
        const source = data && typeof data === 'object' ? data : {};
        const w = Number(source.width || width || WIDTH) || WIDTH;
        const h = Number(source.height || height || HEIGHT) || HEIGHT;
        const raw = source.people?.[0]?.pose_keypoints_2d;
        const points = [];
        for(let i = 0; i < KEYPOINTS.length; i += 1){
            const fallback = DEFAULT_POINTS[i];
            points.push([
                clamp(Array.isArray(raw) ? raw[i * 3] : fallback[0], 0, w),
                clamp(Array.isArray(raw) ? raw[i * 3 + 1] : fallback[1], 0, h),
                Array.isArray(raw) ? (Number(raw[i * 3 + 2]) > 0 ? 1 : 0) : 1
            ]);
        }
        return {width:w, height:h, people:[{pose_keypoints_2d:keypointsArrayFromPoints(points)}]};
    }

    function posePoints(data){
        const pose = normalizePoseData(data);
        const raw = pose.people[0].pose_keypoints_2d;
        return KEYPOINTS.map((name, i) => ({
            name,
            x:Number(raw[i * 3]) || 0,
            y:Number(raw[i * 3 + 1]) || 0,
            v:Number(raw[i * 3 + 2]) || 0
        }));
    }

    function setPoint(data, index, x, y){
        const pose = normalizePoseData(data);
        const raw = pose.people[0].pose_keypoints_2d.slice();
        raw[index * 3] = clamp(x, 0, pose.width);
        raw[index * 3 + 1] = clamp(y, 0, pose.height);
        raw[index * 3 + 2] = 1;
        pose.people[0].pose_keypoints_2d = raw;
        return pose;
    }

    function mirrorPose(data){
        const pose = normalizePoseData(data);
        const raw = pose.people[0].pose_keypoints_2d.slice();
        for(let i = 0; i < KEYPOINTS.length; i += 1){
            raw[i * 3] = pose.width - (Number(raw[i * 3]) || 0);
        }
        const pairs = [[2,5], [3,6], [4,7], [8,11], [9,12], [10,13], [14,15], [16,17]];
        pairs.forEach(([a,b]) => {
            for(let k = 0; k < 3; k += 1){
                const ai = a * 3 + k, bi = b * 3 + k;
                const temp = raw[ai];
                raw[ai] = raw[bi];
                raw[bi] = temp;
            }
        });
        pose.people[0].pose_keypoints_2d = raw;
        return pose;
    }

    function drawPose(ctx, poseData, options={}){
        const pose = normalizePoseData(poseData);
        const scaleX = ctx.canvas.width / pose.width;
        const scaleY = ctx.canvas.height / pose.height;
        const points = posePoints(pose);
        ctx.save();
        ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        ctx.fillStyle = options.transparent ? 'rgba(0,0,0,0)' : '#020617';
        ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        LIMBS.forEach(([a,b,color]) => {
            const p1 = points[a], p2 = points[b];
            if(!p1?.v || !p2?.v) return;
            ctx.strokeStyle = color;
            ctx.lineWidth = Math.max(5, 12 * Math.min(scaleX, scaleY));
            ctx.beginPath();
            ctx.moveTo(p1.x * scaleX, p1.y * scaleY);
            ctx.lineTo(p2.x * scaleX, p2.y * scaleY);
            ctx.stroke();
        });
        points.forEach((p, i) => {
            if(!p.v) return;
            ctx.fillStyle = i === options.activeIndex ? '#ffffff' : '#38bdf8';
            ctx.strokeStyle = '#0f172a';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.arc(p.x * scaleX, p.y * scaleY, Math.max(4, 6 * Math.min(scaleX, scaleY)), 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
        });
        ctx.restore();
    }

    function poseToDataUrl(poseData, options={}){
        const pose = normalizePoseData(poseData);
        const canvas = document.createElement('canvas');
        canvas.width = Number(options.width || pose.width || WIDTH) || WIDTH;
        canvas.height = Number(options.height || pose.height || HEIGHT) || HEIGHT;
        drawPose(canvas.getContext('2d'), pose, options);
        return canvas.toDataURL('image/png');
    }

    function hitTest(canvas, poseData, clientX, clientY, radius=18){
        const rect = canvas.getBoundingClientRect();
        const pose = normalizePoseData(poseData);
        const x = (clientX - rect.left) / rect.width * pose.width;
        const y = (clientY - rect.top) / rect.height * pose.height;
        let best = {index:-1, distance:Infinity, x, y};
        posePoints(pose).forEach((p, i) => {
            const d = Math.hypot(p.x - x, p.y - y);
            if(d < best.distance) best = {index:i, distance:d, x, y};
        });
        return best.distance <= radius ? best : {index:-1, distance:best.distance, x, y};
    }

    global.CanvasPoseEditor = Object.freeze({
        WIDTH,
        HEIGHT,
        KEYPOINTS,
        LIMBS,
        defaultPoseData,
        normalizePoseData,
        posePoints,
        setPoint,
        mirrorPose,
        drawPose,
        poseToDataUrl,
        hitTest
    });
})(window);
