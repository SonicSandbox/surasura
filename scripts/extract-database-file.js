// Extract Migaku Database File (No External Dependencies)
// Run this in Console on a Migaku extension page

(async function extractDatabase() {
    console.log('🔍 Extracting Migaku Database...');

    try {
        function openDB(name) {
            return new Promise((resolve, reject) => {
                const request = indexedDB.open(name);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        function getFromStore(store, key) {
            return new Promise((resolve, reject) => {
                const request = store.get(key);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        async function decompressGzip(data) {
            const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream('gzip'));
            const response = new Response(stream);
            return await response.arrayBuffer();
        }

        // Get user ID
        console.log('🔐 Getting user ID...');
        const firebaseDB = await openDB('firebaseLocalStorageDb');
        const tx = firebaseDB.transaction('firebaseLocalStorage', 'readonly');
        const store = tx.objectStore('firebaseLocalStorage');

        const authKey = 'firebase:authUser:AIzaSyDZvwYKYTsQoZkf3oKsfIQ4ykuy2GZAiH8:[DEFAULT]';
        const authData = await getFromStore(store, authKey);
        firebaseDB.close();

        const userData = authData?.value || authData;
        const uid = userData?.uid || 'OSgSaZn1apXewxVFrtNW6VTCK6r1'; // Fallback to your known UID

        console.log(`✓ User ID: ${uid}`);

        // Get database
        console.log('\n💾 Extracting database...');
        const srsDB = await openDB('srs');
        const dataTx = srsDB.transaction('data', 'readonly');
        const dataStore = dataTx.objectStore('data');

        const dbKey = `core_${uid}.db`;
        const dbData = await getFromStore(dataStore, dbKey);
        srsDB.close();

        if (!dbData || !dbData.data) {
            throw new Error('Database not found');
        }

        const sizeKB = (dbData.data.byteLength / 1024).toFixed(2);
        console.log(`✓ Database size: ${sizeKB} KB (compressed)`);

        // Download compressed version
        console.log('\n📦 Downloading compressed database...');
        let blob = new Blob([dbData.data], { type: 'application/gzip' });
        let url = URL.createObjectURL(blob);
        let a = document.createElement('a');
        a.href = url;
        a.download = `migaku-db-${uid}-compressed.db.gz`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        console.log('✅ Downloaded: migaku-db-compressed.db.gz');

        // Decompress and download
        console.log('\n📦 Decompressing...');
        const decompressed = await decompressGzip(dbData.data);
        const decompressedSizeKB = (decompressed.byteLength / 1024).toFixed(2);
        console.log(`✓ Decompressed size: ${decompressedSizeKB} KB`);

        blob = new Blob([decompressed], { type: 'application/x-sqlite3' });
        url = URL.createObjectURL(blob);
        a = document.createElement('a');
        a.href = url;
        a.download = `migaku-dictionary-${uid}.db`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        console.log('✅ Downloaded: migaku-dictionary.db');
        console.log('\n🎉 Success! Database file extracted.');
        console.log('\nNext steps:');
        console.log('1. Open the .db file with SQLite tools (DB Browser for SQLite, sqlite3 CLI, etc.)');
        console.log('2. Query the WordList table');
        console.log('3. Export to JSON/CSV as needed');

        return { success: true, userId: uid, sizeKB: decompressedSizeKB };

    } catch (error) {
        console.error('❌ Error:', error);
        throw error;
    }
})();