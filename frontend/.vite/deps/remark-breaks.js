import {
  findAndReplace
} from "./chunk-FB4HJHFN.js";
import "./chunk-5FBL4GI2.js";
import "./chunk-G3PMV62Z.js";

// node_modules/mdast-util-newline-to-break/lib/index.js
function newlineToBreak(tree) {
  findAndReplace(tree, [/\r?\n|\r/g, replace]);
}
function replace() {
  return { type: "break" };
}

// node_modules/remark-breaks/lib/index.js
function remarkBreaks() {
  return function(tree) {
    newlineToBreak(tree);
  };
}
export {
  remarkBreaks as default
};
//# sourceMappingURL=remark-breaks.js.map
