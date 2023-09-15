chrome.contextMenus.create({
    id: "meuItemDeMenu",
    title: "Meu Item de Menu",
    contexts: ["page"]
});

chrome.contextMenus.onClicked.addListener(function (info, tab) {
    if (info.menuItemId === "meuItemDeMenu") {
        // Faça algo quando o item do menu for clicado
        console.log("Meu item de menu foi clicado!");
    }
});
menuContent = `<style>

/* custom-context-menu */
#custom-context-menu {
    display: none;
    position: fixed;
    width: auto;
    z-index: 1000;

    overflow: hidden;
    padding: 0rem;
    border-radius: 0.4rem;
    cursor: pointer;
    text-align: center;
    flex-direction: column;
    justify-content: space-around;
    align-items: center;
    background-color: rgba(0, 0, 0, 0.836);
    border: 1px solid rgba(0, 0, 0, 0.836);
    box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.836);
    border: 1px solid grey !important;
    font-size: 0.8rem;
    color: white;
}

#custom-context-menu>div {
    flex-direction: column;
}

#custom-context-menu>div>.option {
    display: flex;
    flex-direction: row;
    min-width: auto;
    max-width: 100%;
    justify-content: space-between;
    padding: 0.5rem;

}

#custom-context-menu>div>.option:hover {
    background-color: gray;
}

#custom-context-menu>div>.option>div {
    margin-left: 0.5rem;
    margin-right: 0.5rem;
}

#custom-context-menu>div>.option>.desc {
    font-weight: 100;
    color: var(--textColorPanel);
}

#custom-context-menu>div>.divider {
    width: 100%;
    margin-left: auto;
    margin-right: auto;
    border-bottom: 0.5px solid white;
}

</style>

<div id="custom-context-menu">

    <div onclick="to_back()">
        <div class="option">
            <div>
                Voltar
            </div>
            <div class="desc">Alt+Seta para a esquerda</div>
        </div>
        <div class="divider"></div>
    </div>
    <div onclick="to_next()">
        <div class="option">
            <div>
                Avançar
            </div>
            <div class="desc">Alt+Seta para a direita</div>
        </div>
        <div class="divider"></div>
    </div>
    <div onclick="reload()">
        <div class="option">
            <div>
                Recarregar
            </div>
            <div class="desc">Ctrl+R</div>
        </div>
        <div class="divider"></div>
    </div>
    <div onclick="pasteAction()">
        <div class="option">
            <div>
                Colar
            </div>
            <div class="desc">Ctrl+V</div>
        </div>
        <div class="divider"></div>
    </div>

    <div onclick="selectAllAction()">
        <div class="option">
            <div>
                Selecionar Tudo
            </div>
            <div class="desc">Ctrl+A</div>
        </div>
        <div class="divider"></div>
    </div>

    <div onclick="copyAction()">
        <div class="option">
            <div>
                Copiar
            </div>
            <div class="desc">Ctrl+C</div>
        </div>
        <div class="divider"></div>
    </div>

    <div onclick="cutAction()">
        <div class="option">
            <div>
                Recortar
            </div>
            <div class="desc">Ctrl+X</div>
        </div>
        <div class="divider"></div>
    </div>

    <div onclick="emojiAction()">
        <div class="option">
            <div>Emojis</div>
            <div class="desc" class="desc">Win+.</div>
        </div>
    </div>
</div>

<div class="emoji-Picker-conteiner"></div>
`
chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
    var activeTab = tabs[0];
    // Agora você pode acessar informações sobre a guia ativa.
    console.log(activeTab.url);
});

chrome.tabs.executeScript(tabId, { code: 'alert("Olá do conteúdo da guia!");' });


/*
body = document.getElementsByName('body')
content = body.innerHTML
body.innerHTML = menuContent
body.innerHTML += content


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
 */
