export interface FileItem {
    name: string;
    path: string;
    type: 'file' | 'directory' | 'link';
    target?: string; // For links
    size?: number | null;
    mtime?: number | null;
    ignored?: boolean | null;
    media?: string[]; // Media it's on (for index browsing)
    selected?: boolean; // For restore cart
    sha256_hash?: string | null;
    vulnerable?: boolean;
    indeterminate?: boolean;
    // Discrepancy fields
    discrepancy_id?: number;
    is_deleted?: boolean;
    has_versions?: boolean;
}

export interface TreeNode {
    name: string;
    path: string;
    children?: TreeNode[];
    expanded?: boolean;
    hasChildren?: boolean;
    discrepancy_count?: number;
}

export interface Breadcrumb {
    name: string;
    path: string;
}

export interface TreemapItem {
    label: string;
    value: number;
    color?: string;
    fullPath?: string;
    children?: TreemapItem[];
}

// Discriminated union for media creation
export interface LtoTapeCreateData {
    media_type: 'lto_tape';
    identifier: string;
    capacity: number;
    location?: string;
    location_building?: string;
    location_room?: string;
    location_rack?: string;
    location_slot?: string;
    generation: string;
    worm?: boolean;
    write_protected?: boolean;
    compression?: boolean;
    encryption_key_id?: string;
    cleaning_cartridge?: boolean;
}

export interface OfflineHddCreateData {
    media_type: 'local_hdd';
    identifier: string;
    capacity: number;
    location?: string;
    location_building?: string;
    location_room?: string;
    location_rack?: string;
    location_slot?: string;
    drive_model?: string;
    device_uuid?: string;
    is_ssd?: boolean;
    mount_path?: string;
    filesystem_type?: string;
    connection_interface?: string;
    encrypted?: boolean;
    encryption_key_id?: string;
}

export interface CloudCreateData {
    media_type: 's3_compat';
    identifier: string;
    capacity: number;
    location?: string;
    location_building?: string;
    location_room?: string;
    location_rack?: string;
    location_slot?: string;
    provider_template: string;
    endpoint_url: string;
    region: string;
    bucket_name: string;
    access_key_id: string;
    secret_access_key: string;
    path_style_access?: boolean;
    storage_class?: string;
    max_part_size_mb?: number;
    obfuscate_filenames?: boolean;
    client_side_encryption_passphrase?: string;
}

export type MediaCreateData = LtoTapeCreateData | OfflineHddCreateData | CloudCreateData;

// LTO Generation capacity mapping (in GB, base-10)
export const LTO_CAPACITY: Record<string, number> = {
    'LTO-5': 1500, // 1.5 TB
    'LTO-6': 2500, // 2.5 TB
    'LTO-7': 6000, // 6.0 TB
    'LTO-8': 12000, // 12.0 TB
    'LTO-9': 18000, // 18.0 TB
};

// Provider template defaults
export const PROVIDER_TEMPLATES: Record<string, { endpoint: string; region: string }> = {
    'aws': { endpoint: 's3.amazonaws.com', region: 'us-east-1' },
    'minio': { endpoint: '', region: 'us-east-1' },
    'wasabi': { endpoint: 's3.wasabisys.com', region: 'us-east-1' },
    'backblaze': { endpoint: 's3.us-west-002.backblazeb2.com', region: 'us-west-002' },
    'digitalocean': { endpoint: '', region: 'nyc3' },
    'custom': { endpoint: '', region: 'us-east-1' },
};
