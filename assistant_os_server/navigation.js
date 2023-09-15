
const apps_conteiner = document.querySelector('.apps_conteiner')
const opening_app_conteiner = document.querySelector('.opening_app_conteiner')

apps_list = {}
function get_apps_data() {
    try {
        if (sessionStorage[`apps_data`] == undefined) {
            fetch(`apps_registered.json`, {
                method: "GET"
            }).then(response => {
                response.json()
                    .then(data => {
                        sessionStorage[`apps_data`] = JSON.stringify(data)
                        render_apps_list(JSON.parse(sessionStorage[`apps_data`]))
                        apps_list = data
                        return data
                    }

                    )
            })
        }

        apps_data = JSON.parse(sessionStorage[`apps_data`])
        return apps_data
    } catch (error) {
        console.log(error)
    }
}

apps_list = get_apps_data()

// Função para lidar com eventos de teclado
function handleKeyPress(event) {

    if (event.key === "ArrowRight") {
        checkActiveElement()
        // Mova para o próximo elemento à direita
        document.getElementById(document.activeElement.id).nextElementSibling.focus();
    } else if (event.key === "ArrowLeft") {
        checkActiveElement()
        // Mova para o próximo elemento à esquerda
        document.getElementById(document.activeElement.id).previousElementSibling.focus();
    }
}

function checkActiveElement() {
    var ActiveElement = document.activeElement;
    if (ActiveElement.className != 'app') {
        document.getElementById('app_1').focus();
    }
}
// Adicione um ouvinte de evento ao documento para capturar as teclas pressionadas
document.addEventListener("keydown", handleKeyPress);

// Função para lidar com o clique no elemento selecionado
function elementoSelecionado(element) {
    alert("Elemento selecionado: " + element.textContent);
}

// Adicionar ouvinte de evento para a tecla Enter
document.addEventListener("keydown", function (event) {
    if (event.key === "Enter") {
        var elementoSelecionado = document.querySelector(":focus");
        if (elementoSelecionado) {
            elementoSelecionado.click(); // Simula um clique no elemento selecionado
        }
    }
});



function getItemById(id) {
    const apps = apps_list.apps;
    for (let i = 0; i < apps.length; i++) {
        if (apps[i].id === id) {
            return apps[i];
        }
    }

    return null; // Retorna null se não encontrar um valor com o ID fornecido
}

function open_app(id) {
    app = getItemById(id)
    opening_app_conteiner.querySelector('img').src = app['icon_path']
    opening_app_conteiner.style.display = 'flex'
    setTimeout(() => {
        window.location.href = app['url']
    }, 25)
}

function render_apps_list(data) {
    let apps_list_ = apps_list
    if (data) {
        apps_list_ = data
    }
    for (app_count = 0; app_count < apps_list_['apps'].length; app_count++) {
        let app = apps_list_['apps'][app_count]
        apps_conteiner.innerHTML += `
        <!-- ${app['name']} -->
        <div class="app" id="app_${app['id']}" title="${app['name']} APP" onclick="open_app(${app['id']})" tabindex="1">
            <img src="${app['icon_path']}" alt="${app['name']} logo">
            <div class="app_decription">${app['name']}</div>
        </div>`
    }
}

setInterval(()=>{
    opening_app_conteiner.style.display = 'none'},1000)

opening_app_conteiner.style.display = 'none'
render_apps_list()


