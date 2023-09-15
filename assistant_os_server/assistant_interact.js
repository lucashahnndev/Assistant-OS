
const assistantInteraction = document.querySelector('.assistant-interaction')
function openAssistantinteract(){
    assistantInteraction.style.display = 'flex'
}

function closeAssistantInteract(){

    assistantInteraction.style.display = 'none'
}

//events =========
document.addEventListener('click', evt => {
    try {
        disable_assistant_interact = false
        if (evt.srcElement == document.querySelector('body')) {
            disable_assistant_interact = true
        }
        if (evt.srcElement == document.querySelector('#main')) {
            disable_assistant_interact = true
        }

        if (evt.srcElement == document.querySelector('.status_bar')) {
            disable_assistant_interact = true
        }
        if (evt.srcElement == document.querySelector('.apps_conteiner')) {
            disable_assistant_interact = true
        }
        if (disable_assistant_interact == true) {
            closeAssistantInteract()
        }
    } catch (error) {
        console.log(error)
    }

}, true);
