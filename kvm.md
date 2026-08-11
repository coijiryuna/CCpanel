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
-net user,hostfwd=tcp::8888-:8888,hostfwd=tcp::2222-:22

ssh user-vm@localhost -p 2222


==================================================
Selesai. Panel jalan: http://127.0.0.1:8888
Login: admin / R6Zed0SPO7sRUP7QVBsRL9iSAE4ziWQs
Credential tersimpan di /etc/ccpanel.env (mode 600)
==================================================
Akses remote via SSH tunnel:
  ssh -L 8888:127.0.0.1:8888 user@vps-ip