declare module 'cytoscape-fcose' {
  const ext: cytoscape.Ext;
  export default ext;
}

declare module 'cytoscape-dagre' {
  const ext: cytoscape.Ext;
  export default ext;
}

declare module 'cytoscape-cola' {
  const ext: cytoscape.Ext;
  export default ext;
}

declare module 'cytoscape-elk' {
  const ext: cytoscape.Ext;
  export default ext;
}

declare module 'cytoscape-context-menus' {
  const ext: cytoscape.Ext;
  export default ext;
}

declare namespace cytoscape {
  interface Core {
    contextMenus(options: ContextMenusOptions): ContextMenusInstance;
    contextMenus(action: 'get'): ContextMenusInstance;
  }

  interface ContextMenusOptions {
    evtType?: string;
    menuItems?: ContextMenuItem[];
    menuItemClasses?: string[];
    contextMenuClasses?: string[];
  }

  interface ContextMenuItem {
    id: string;
    content: string;
    tooltipText?: string;
    selector?: string;
    coreAsWell?: boolean;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    onClickFunction?: (event: any) => void;
    disabled?: boolean;
    show?: boolean;
    hasTrailingDivider?: boolean;
    submenu?: ContextMenuItem[];
  }

  interface ContextMenusInstance {
    destroy(): void;
    isActive(): boolean;
    appendMenuItem(item: ContextMenuItem, parentID?: string): void;
    removeMenuItem(itemID: string): void;
    disableMenuItem(itemID: string): void;
    enableMenuItem(itemID: string): void;
    showMenuItem(itemID: string): void;
    hideMenuItem(itemID: string): void;
  }
}
