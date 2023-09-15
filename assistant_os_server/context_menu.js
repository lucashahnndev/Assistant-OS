emojiOptionPosX = 0
emojiOptionPosY = 0
element_selected = ''

function showContextMenu(event) {
    event.preventDefault();

    const contextMenu = document.getElementById('custom-context-menu');
    contextMenu.style.display = 'block';
    contextMenu.style.left = event.clientX + 'px';
    contextMenu.style.top = event.clientY + 'px';
    emojiOptionPosX = event.clientX + 'px';
    emojiOptionPosY = event.clientY + 'px';

    const isInput = event.target.tagName === 'INPUT';
    const isTextarea = event.target.tagName === 'TEXTAREA';
    const pasteOption = contextMenu.querySelector('[onclick="pasteAction()"]');
    const selectAllOption = contextMenu.querySelector('[onclick="selectAllAction()"]');
    const copyOption = contextMenu.querySelector('[onclick="copyAction()"]');
    const cutOption = contextMenu.querySelector('[onclick="cutAction()"]');
    const emojiOption = contextMenu.querySelector('[onclick="emojiAction()"]');


    element_selected = event.target
    pasteOption.style.display = (isInput || isTextarea) ? 'flex' : 'none';
    selectAllOption.style.display = (isInput || isTextarea) ? 'flex' : 'none';

    copyOption.style.display = (isInput || isTextarea) && window.getSelection().toString() !== '' ? 'flex' : 'none';
    cutOption.style.display = (isInput || isTextarea) && window.getSelection().toString() !== '' ? 'flex' : 'none';

    emojiOption.style.display = (isInput || isTextarea) ? 'flex' : 'none';
    if (isInput == false && isTextarea == false && window.getSelection().toString() != '') {

        hideContextMenu()
    }
}

function getSelectedText() {
    let selectedText = '';

    if (window.getSelection) {
        selectedText = window.getSelection().toString();
        console.log(window.getSelection())
    } else if (document.selection && document.selection.type != 'Control') {
        selectedText = document.selection.createRange().text;
        console.log(document.selection.createRange())
    }

    return selectedText;
}

function to_back() {
    history.go(-1)
}

function to_next() {
    history.go(+1)
}
function reload() {
    window.location.href = ''
}


function pasteAction() {

    // Função assíncrona para ler o texto da área de transferência
    async function getTextInClipboard() {
        try {
            // Leia o texto da área de transferência
            const getTextClipboard = await navigator.clipboard.readText();
            return getTextClipboard;
        } catch (error) {
            console.error('Erro ao colar da área de transferência: ', error);
            return ''; // Retorna uma string vazia em caso de erro
        }
    }

    // Chame a função assíncrona e atualize o valor do elemento de input quando a operação estiver concluída
    getTextInClipboard().then((text) => {
        if (getSelectedText()) {
            element_selected.value = element_selected.value.replace(getSelectedText(), text)
        }
        element_selected.value += text;
    });
    hideContextMenu();
}

function selectAllAction() {
    document.execCommand('selectAll');
    hideContextMenu();
}

function copyAction() {
    document.execCommand('copy');
    hideContextMenu();
}

function cutAction() {
    document.execCommand('cut');
    hideContextMenu();
}

function emojiInput(emoji) {
    element_selected.value += emoji.native
}


function emojiAction() {

    const pickerOptions = {
        onEmojiSelect: emojiInput,
        locale: 'pt',
        theme: theme,



    }
    const picker = new EmojiMart.Picker(pickerOptions)
    emojiPickerconteiner = document.querySelector('.emoji-Picker-conteiner')
    emojiPickerconteiner.style.display = 'block'

    emojiPickerconteiner.innerHTML = ''
    emojiPickerconteiner.appendChild(picker)
    emEmojiPicker = emojiPickerconteiner.querySelector('em-emoji-picker')
    emEmojiPicker.style.left = emojiOptionPosX
    hideContextMenu();
}

function hideContextMenu() {
    const contextMenu = document.getElementById('custom-context-menu');
    contextMenu.style.display = 'none';
}




//events =========
document.addEventListener('click', evt => {
    try {
        if (evt.srcElement != document.getElementById('custom-context-menu')) {
            document.getElementById('custom-context-menu').style.display = 'none';

        }
    } catch (error) {
        console.log(error)
    }

}, true);
