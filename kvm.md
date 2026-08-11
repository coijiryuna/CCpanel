# Cek apakah KVM aktif (harus muncul angka lebih dari 0)
kvm-ok || lscpu | grep Virtualization

# Tambahkan user Anda ke grup kvm & libvirt agar tidak perlu selalu mengetik 'sudo'
sudo usermod -aG kvm,libvirt $USER
qemu-img create -f qcow2 server-test.qcow2 20G



qemu-system-x86_64 -enable-kvm -m 2G -smp 2 \
-hda server-test.qcow2 \
-cdrom /home/coijiryuna/Downloads/debian-minimal.iso \
-boot d

qemu-system-x86_64 -enable-kvm -m 2G -smp 2 \
-hda server-test.qcow2 \
-nographic \
-net nic,model=virtio \
-net user,hostfwd=tcp::8080-:8080,hostfwd=tcp::2222-:22

ssh user-vm@localhost -p 2222
