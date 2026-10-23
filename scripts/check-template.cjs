// Compile Vue directives without driving a browser; this is not a visual test.
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const root = path.resolve(__dirname, '..');
const context = { console };
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root, 'web/vendor/vue.global.prod.js'), 'utf8'), context);
const html = fs.readFileSync(path.join(root, 'web/index.html'), 'utf8');
const template = html.slice(html.indexOf('<div id="app"'), html.indexOf('<div id="boot-error"'));
context.Vue.compile(template, {decodeEntities: text => text.replace(/&(amp|lt|gt|quot|apos);/g,
  (_, name) => ({amp:'&',lt:'<',gt:'>',quot:'"',apos:"'"})[name])});
console.log('Vue template compiled');
