export interface FileItem {
    name: string;
    path: string;
    type: 'file' | 'directory' | 'link';
    target?: string; // For links
    size?: number | null;
    mtime?: number | null;
    tracked?: boolean | null;
    ignored?: boolean | null;
    media?: string[]; // Media it's on (for index browsing)
    selected?: boolean; // For restore cart
    sha256_hash?: string | null;
    vulnerable?: boolean;
    indeterminate?: boolean;
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
