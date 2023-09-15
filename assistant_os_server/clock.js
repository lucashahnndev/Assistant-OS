
function formateDateHour(date) {
    const day = String(date.getDate()).padStart(2, '0');
    const mounth = String(date.getMonth() + 1).padStart(2, '0');
    const year = String(date.getFullYear()).slice(-2);
    const hour = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');

    return `${hour}:${minutes} ${day}/${mounth}/${year}`;
}

function updateClock() {
    setInterval(() => {
        var divdateHour = document.querySelector(".clock");

        const dateHourNow = new Date();
        const dateHourFormated = formateDateHour(dateHourNow)

        divdateHour.textContent = dateHourFormated

    }, 1000)
}
updateClock();

var calendarEl = document.getElementById('calendar');
var calendar = new FullCalendar.Calendar(calendarEl, {

    initialView: 'dayGridMonth',
    views: {
        dayGridMonth: { // name of view
            titleFormat: { year: 'numeric', month: '2-digit', day: '2-digit' }
            // other view-specific options here
        }
    }
});

calendar.setOption('locale', 'br');
function openCalendar() {
    try {
        if (calendar.isRendering == true) {
            calendar.destroy();
        } else {
            calendar.render();

        }

    } catch { }
}

//events =========
document.addEventListener('click', evt => {
    try {
        disable_calendar = false
        if (evt.srcElement == document.querySelector('body')) {
            disable_calendar = true
        }
        if (evt.srcElement == document.querySelector('#main')) {
            disable_calendar = true
        }

        if (evt.srcElement == document.querySelector('.status_bar')) {
            disable_calendar = true
        }
        if (evt.srcElement == document.querySelector('.apps_conteiner')) {
            disable_calendar = true
        }
        if (disable_calendar == true) {
            calendar.destroy()
        }
    } catch (error) {
        console.log(error)
    }

}, true);

