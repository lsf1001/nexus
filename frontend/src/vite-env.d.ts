/// <reference types="vite/client" />

declare module '*.gif' {
  const content: string;
  export default content;
}

declare module '*.png' {
  const content: string;
  export default content;
}

declare module '*.svg' {
  const content: string;
  export default content;
}

declare module 'qrcode' {
  function toDataURL(text: string, options?: object): Promise<string>;
  function toCanvas(canvas: HTMLCanvasElement, text: string, options?: object): Promise<void>;
  export = { toDataURL, toCanvas };
}
