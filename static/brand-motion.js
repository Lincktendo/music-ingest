'use strict';

// A small solid model of Lincktendo's four pillars, rendered locally with alpha.
// The favicon continues to use the existing static image.
(() => {
  document.body.classList.remove('brand-playing');
  let latestDownloads = 0, updateModel = null;
  window.addEventListener('music-ingest:downloads-state',event=>{
    const count=Number(event.detail?.active);
    latestDownloads=Number.isFinite(count) ? Math.max(0,Math.floor(count)) : 0;
    document.body.classList.toggle('brand-download-active',latestDownloads>0);
    const mobile=document.querySelector('.mobile-brand');
    if(mobile) mobile.title=latestDownloads>0 ? 'Descargas en curso' : '';
    updateModel?.(latestDownloads);
  });
  const link = document.querySelector('.sidebar .brand');
  const holder = link?.querySelector('.brand-icon');
  if (!holder) return;
  const canvas = document.createElement('canvas');
  canvas.className = 'brand-motion';
  canvas.setAttribute('aria-label', 'Tocá para ir a Inicio. Arrastrá el logo para girarlo.');
  canvas.setAttribute('role', 'button');
  canvas.tabIndex = 0;
  holder.removeAttribute('aria-hidden');
  const gl = canvas.getContext('webgl', {alpha:true, antialias:true, premultipliedAlpha:false});
  if (!gl) return;
  holder.append(canvas);

  const palette = {
    blue:[.07,.13,.68], green:[.08,.48,.22], red:[.68,.08,.05],
    gold:[.88,.61,.04], underside:[.055,.075,.18]
  };
  const vertices = [];
  const cells = new Set();
  const cellKey = (x,y,z) => [x,y,z].join(',');
  for (let x=-1;x<=1;x++) for (let z=-1;z<=1;z++) {
    if (x===0 && z===0) continue;
    const height = Math.abs(x)===1 && Math.abs(z)===1 ? 3 : 1;
    for (let y=0;y<height;y++) cells.add(cellKey(x,y,z));
  }
  const faces = [
    {normal:[1,0,0], corners:[[.5,-.5,-.5],[.5,.5,-.5],[.5,.5,.5],[.5,-.5,.5]]},
    {normal:[-1,0,0],corners:[[-.5,-.5,.5],[-.5,.5,.5],[-.5,.5,-.5],[-.5,-.5,-.5]]},
    {normal:[0,1,0], corners:[[-.5,.5,-.5],[-.5,.5,.5],[.5,.5,.5],[.5,.5,-.5]]},
    {normal:[0,-1,0],corners:[[-.5,-.5,.5],[-.5,-.5,-.5],[.5,-.5,-.5],[.5,-.5,.5]]},
    {normal:[0,0,1], corners:[[.5,-.5,.5],[.5,.5,.5],[-.5,.5,.5],[-.5,-.5,.5]]},
    {normal:[0,0,-1],corners:[[-.5,-.5,-.5],[-.5,.5,-.5],[.5,.5,-.5],[.5,-.5,-.5]]}
  ];
  for (const key of cells) {
    const [x,y,z] = key.split(',').map(Number);
    for (const face of faces) {
      const [nx,ny,nz] = face.normal;
      if (cells.has(cellKey(x+nx,y+ny,z+nz))) continue;
      let color;
      if (ny>0) color = y===2 ? palette.gold : palette.red;
      else if (ny<0) color = palette.underside;
      else if (nx) {
        color = nx*z>=0 ? (nx*x>0 ? palette.blue : palette.red) : palette.green;
      } else {
        color = nz*x<=0 ? (nz*z>0 ? palette.blue : palette.red) : palette.green;
      }
      for (const index of [0,1,2,0,2,3]) {
        const point = face.corners[index];
        vertices.push(x+point[0], y+point[1]-1, z+point[2], ...color, nx,ny,nz);
      }
    }
  }

  const vertexSource = `
    attribute vec3 position;
    attribute vec3 color;
    attribute vec3 normal;
    uniform mat3 rotation;
    uniform vec2 fit;
    varying vec3 shaded;
    varying vec3 surfaceNormal;
    varying vec3 surfacePosition;
    void main() {
      vec3 p = rotation * position;
      vec3 n = rotation * normal;
      float light = .78 + .22 * max(dot(n, normalize(vec3(-.3,.7,1.))),0.);
      shaded = color * light;
      surfaceNormal = n;
      surfacePosition = p;
      gl_Position = vec4(p.xy * fit, -p.z * .18, 1.);
    }`;
  const fragmentSource = `
    precision mediump float;
    varying vec3 shaded;
    varying vec3 surfaceNormal;
    varying vec3 surfacePosition;
    uniform float charge;
    uniform float shimmerTime;
    void main() {
      vec3 n = normalize(surfaceNormal);
      vec3 reflection = reflect(vec3(0.,0.,-1.),n);
      // Broad studio reflections and narrow highlights keep each flat face legible.
      float sweep = reflection.y * 5.4 + surfacePosition.y * .75;
      float softBand = .5 + .5 * sin(sweep + reflection.x * 2.2);
      float sharpBand = pow(.5 + .5 * sin(sweep * 1.7 + shimmerTime * .3),16.);
      float rim = pow(1. - abs(n.z),3.);
      vec3 silver = mix(vec3(.075,.10,.16),vec3(.70,.76,.83),softBand);
      float angle = reflection.x * 3.2 + reflection.z * 2.4 + surfacePosition.y * .28 + shimmerTime * .22;
      vec3 spectrum = .5 + .5 * cos(angle + vec3(0.,2.094,4.188));
      vec3 chrome = silver + (spectrum-.5) * (.12 + .1 * rim);
      chrome += vec3(.70,.76,.83) * sharpBand * .56 + spectrum * rim * .10;
      gl_FragColor = vec4(mix(shaded,clamp(chrome,0.,1.),charge),1.);
    }`;
  let program, buffer, rotationLocation, fitLocation, chargeLocation, shimmerLocation;
  function shader(type, source) {
    const result = gl.createShader(type);
    gl.shaderSource(result,source);gl.compileShader(result);
    if (!gl.getShaderParameter(result,gl.COMPILE_STATUS)) {
      gl.deleteShader(result);throw Error('Logo shader unavailable');
    }
    return result;
  }
  function prepare() {
    const vertex = shader(gl.VERTEX_SHADER,vertexSource);
    const fragment = shader(gl.FRAGMENT_SHADER,fragmentSource);
    program = gl.createProgram();gl.attachShader(program,vertex);gl.attachShader(program,fragment);
    gl.linkProgram(program);gl.deleteShader(vertex);gl.deleteShader(fragment);
    if (!gl.getProgramParameter(program,gl.LINK_STATUS)) throw Error('Logo unavailable');
    gl.useProgram(program);
    buffer = gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
    gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(vertices),gl.STATIC_DRAW);
    for (const [index,name] of ['position','color','normal'].entries()) {
      const loc = gl.getAttribLocation(program,name);
      gl.enableVertexAttribArray(loc);gl.vertexAttribPointer(loc,3,gl.FLOAT,false,36,index*12);
    }
    rotationLocation = gl.getUniformLocation(program,'rotation');
    fitLocation = gl.getUniformLocation(program,'fit');
    chargeLocation = gl.getUniformLocation(program,'charge');
    shimmerLocation = gl.getUniformLocation(program,'shimmerTime');
    gl.enable(gl.DEPTH_TEST);gl.disable(gl.CULL_FACE);
    gl.clearColor(0,0,0,0);
    holder.classList.add('is-3d');
  }
  try { prepare(); } catch { canvas.remove();return; }

  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  const neutralPitch = .42;
  let yaw = -.72, pitch = neutralPitch, yawSpeed = .6, pitchSpeed = 0;
  let pointer = null, dragged = false, suppressClick = false, downX = 0, downY = 0;
  let previousX = 0, previousY = 0, previousAt = 0, previousFrame = 0;
  let frame = 0, visible = true, lost = false;
  let activeDownloads = 0, charge = 0, shimmerTime = 0;
  const wrap = angle => Math.atan2(Math.sin(angle),Math.cos(angle));
  const clamp = (value,max) => Math.min(max,Math.max(-max,value));
  function draw() {
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (!width || !height || lost) return;
    const ratio = Math.min(devicePixelRatio || 1,2);
    if (canvas.width!==Math.round(width*ratio) || canvas.height!==Math.round(height*ratio)) {
      canvas.width = Math.round(width*ratio);canvas.height = Math.round(height*ratio);
      gl.viewport(0,0,canvas.width,canvas.height);
    }
    const c=Math.cos(yaw),s=Math.sin(yaw),a=Math.cos(pitch),b=Math.sin(pitch);
    // Yaw around the model, followed by camera-relative pitch.
    gl.uniformMatrix3fv(rotationLocation,false,new Float32Array([c,b*s,-a*s,0,a,b,s,-b*c,a*c]));
    gl.uniform2f(fitLocation,.355,.355*width/height);
    gl.uniform1f(chargeLocation,charge);
    gl.uniform1f(shimmerLocation,shimmerTime);
    holder.style.setProperty('--brand-charge',charge.toFixed(3));
    gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
    gl.drawArrays(gl.TRIANGLES,0,vertices.length/9);
  }
  function tick(now) {
    frame=0;
    if (document.hidden || !visible || lost) {previousFrame=0;return;}
    const dt=previousFrame ? Math.min((now-previousFrame)/1000,.04) : 0;
    previousFrame=now;
    const targetCharge = activeDownloads>0 ? 1 : 0;
    charge += (targetCharge-charge)*(1-Math.exp(-dt*4.8));
    if (Math.abs(targetCharge-charge)<.002) charge=targetCharge;
    if (!motion.matches && charge>0) shimmerTime=(shimmerTime+dt)%(Math.PI*100);
    if (pointer===null) {
      const idle=motion.matches ? 0 : .6;
      yawSpeed += (idle-yawSpeed)*(1-Math.exp(-dt*1.2));
      pitchSpeed += (-1.8*wrap(pitch-neutralPitch)-2.3*pitchSpeed)*dt;
      yaw=wrap(yaw+yawSpeed*dt);pitch=wrap(pitch+pitchSpeed*dt);
    }
    draw();
    if (!motion.matches || pointer!==null || Math.abs(targetCharge-charge)>.001 || Math.abs(yawSpeed)>.01 ||
        Math.abs(pitchSpeed)>.01 || Math.abs(wrap(pitch-neutralPitch))>.01) {
      frame=requestAnimationFrame(tick);
    } else previousFrame=0;
  }
  function wake() {
    if (!frame && !document.hidden && visible && !lost) frame=requestAnimationFrame(tick);
  }
  updateModel=count=>{
    activeDownloads=count;
    holder.classList.toggle('is-downloading',activeDownloads>0);
    holder.title=activeDownloads>0 ? (activeDownloads===1?'Una descarga pendiente':activeDownloads+' descargas pendientes') : '';
    wake();
  };
  updateModel(latestDownloads);
  function boost() {
    yawSpeed=clamp(Math.max(yawSpeed,0)+5.4,18);wake();
  }
  function goHome() {
    if (typeof navigate==='function') navigate('inicio');
    else location.hash='inicio';
  }
  canvas.addEventListener('pointerdown',event=>{
    if (event.button!==0 || !event.isPrimary) return;
    pointer=event.pointerId;dragged=false;
    downX=previousX=event.clientX;downY=previousY=event.clientY;
    previousAt=event.timeStamp;canvas.setPointerCapture(pointer);
    canvas.classList.add('is-dragging');holder.classList.add('is-manipulating');wake();
  });
  canvas.addEventListener('pointermove',event=>{
    if (pointer!==event.pointerId) return;
    const dx=event.clientX-previousX,dy=event.clientY-previousY;
    const dt=Math.max(.008,(event.timeStamp-previousAt)/1000);
    if (Math.hypot(event.clientX-downX,event.clientY-downY)>3) dragged=true;
    if (dragged) {
      yaw=wrap(yaw+dx*.03);pitch=wrap(pitch+dy*.03);
      yawSpeed=clamp(yawSpeed*.25+dx*.03/dt*.75,20);
      pitchSpeed=clamp(pitchSpeed*.25+dy*.03/dt*.75,16);
    }
    previousX=event.clientX;previousY=event.clientY;previousAt=event.timeStamp;
    draw();
  });
  function release(event) {
    if (event.pointerId!==pointer) return;
    suppressClick=dragged;
    const held=Math.max(0,(event.timeStamp-previousAt)/1000);
    yawSpeed*=Math.exp(-held*5);pitchSpeed*=Math.exp(-held*5);
    pointer=null;canvas.classList.remove('is-dragging');holder.classList.remove('is-manipulating');wake();
  }
  canvas.addEventListener('pointerup',release);
  canvas.addEventListener('pointercancel',release);
  canvas.addEventListener('lostpointercapture',release);
  canvas.addEventListener('click',event=>{
    event.preventDefault();event.stopPropagation();
    if (suppressClick) {suppressClick=false;return;}
    boost();goHome();
  });
  canvas.addEventListener('keydown',event=>{
    if (event.key==='Enter' || event.key===' ') {
      event.preventDefault();boost();goHome();
    } else if (['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) {
      event.preventDefault();
      if (event.key==='ArrowLeft') yawSpeed-=3;
      if (event.key==='ArrowRight') yawSpeed+=3;
      if (event.key==='ArrowUp') pitchSpeed-=3;
      if (event.key==='ArrowDown') pitchSpeed+=3;
      wake();
    }
  });
  link.addEventListener('dragstart',event=>event.preventDefault());
  canvas.addEventListener('webglcontextlost',event=>{
    event.preventDefault();lost=true;cancelAnimationFrame(frame);frame=0;
    holder.classList.remove('is-3d');
  });
  canvas.addEventListener('webglcontextrestored',()=>{
    try {prepare();lost=false;wake();} catch {holder.classList.remove('is-3d');}
  });
  new IntersectionObserver(entries=>{
    visible=entries[0].isIntersecting;
    if (visible) wake(); else {cancelAnimationFrame(frame);frame=0;previousFrame=0;}
  }).observe(canvas);
  new ResizeObserver(wake).observe(holder);
  document.addEventListener('visibilitychange',wake);
  motion.addEventListener('change',()=>{if(motion.matches)yawSpeed=0;wake();});
  if (motion.matches) yawSpeed=0;
  draw();wake();
})();
