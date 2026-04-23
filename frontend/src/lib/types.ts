export interface FileItem {
    name: string;
    path: string;
    type: 'file' | 'directory' | 'link';
    target?: string; // For links
    size?: number;
    mtime?: number;
    tracked?: boolean;
    media?: string[]; // Media it's on (for index browsing)
    selected?: boolean; // For restore cart
}

export interface TreeNode {
    name: string;
    path: string;
    children?: TreeNode[];
    expanded?: boolean;
}

export interface Breadcrumb {
    name: string;
    path: string;
}
