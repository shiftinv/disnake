// SPDX-License-Identifier: MIT

document.addEventListener(
    "readthedocs-addons-internal-data-ready",
    (event) => {
        const data = event.detail.data(true);
        console.log(data);
        console.log(data.addons.linkpreviews);
        data.addons.linkpreviews = false;
    }
)
