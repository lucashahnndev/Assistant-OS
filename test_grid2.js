const total = 5;
const sx = 100, sy = 0, sz = 0;
let nx = 1, ny = 1, nz = 1;

let activeDims = (sx>0.001?1:0) + (sy>0.001?1:0) + (sz>0.001?1:0);
if(activeDims === 1) {
    nx = sx>0.001 ? total : 1;
    ny = sy>0.001 ? total : 1;
    nz = sz>0.001 ? total : 1;
} else if (activeDims === 2) {
    let area = (sx||1)*(sy||1)*(sz||1);
    let k = Math.sqrt(total/area);
    nx = sx>0.001 ? Math.max(1, Math.round(sx*k)) : 1;
    ny = sy>0.001 ? Math.max(1, Math.round(sy*k)) : 1;
    nz = sz>0.001 ? Math.max(1, Math.round(sz*k)) : 1;
} else {
    let volume = sx * sy * sz || 1;
    let k = Math.pow(total / volume, 1/3);
    nx = Math.max(1, Math.round(sx * k));
    ny = Math.max(1, Math.round(sy * k));
    nz = Math.max(1, Math.round(sz * k));
}
while (nx * ny * nz < total) {
    if (nx <= ny && nx <= nz) nx++;
    else if (ny <= nx && ny <= nz) ny++;
    else nz++;
}

console.log({nx, ny, nz});
