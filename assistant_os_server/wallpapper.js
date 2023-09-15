var main = document.getElementById('main')
function getRandomInt(min, max) {
    return Math.floor(Math.random() * (max - min + 1)) + min;

}

function deviceIsMobile() {
    if (navigator.userAgent.match(/Android/i) ||
        navigator.userAgent.match(/webOS/i) ||
        navigator.userAgent.match(/iPhone/i) ||
        navigator.userAgent.match(/iPad/i) ||
        navigator.userAgent.match(/iPod/i) ||
        navigator.userAgent.match(/BlackBerry/i) ||
        navigator.userAgent.match(/Windows Phone/i)
    ) {
        return true;
    } else {
        return false;
    }

}

function set_wallpapper() {
    if (deviceIsMobile() != true) {
        main.style = `
        background-image: url("image/wallpaper/wallpaper (${getRandomInt(0, 46)}).webp");
        background-repeat: no-repeat;
        background-position: center;
        background-size: 100%;
        animation: zoonImg 60s linear infinite ;`
    }

}

setInterval(() => { set_wallpapper() }, 100000)

set_wallpapper()
