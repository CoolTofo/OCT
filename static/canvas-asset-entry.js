(function(){
    function assetManagerUrl(){
        return '/static/asset-manager.html';
    }

    function openAssetManager(){
        window.open(assetManagerUrl(), '_blank', 'noopener');
    }

    function bindAssetManagerButton(buttonId='assetManagerPageBtn'){
        const button = document.getElementById(buttonId);
        if(!button) return;
        button.addEventListener('click', event => {
            event.preventDefault();
            event.stopPropagation();
            openAssetManager();
        });
    }

    document.addEventListener('DOMContentLoaded', () => bindAssetManagerButton());
    window.CanvasAssetEntry = {assetManagerUrl, openAssetManager, bindAssetManagerButton, lastCanvasId};
})();