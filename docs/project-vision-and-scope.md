# GPU Resource Marketplace
## Project Vision & System Scope

**Version:** 1.0  
**Status:** Approved baseline  
**Project Type:** Web-based Simulation Prototype  
**Approach:** Hybrid GPU Marketplace + HPC Job Scheduling

### 1. Project Overview

GPU Resource Marketplace là một nền tảng web prototype mô phỏng thị trường chia sẻ tài nguyên GPU.

Hệ thống cho phép Worker đăng tài nguyên GPU giả lập, Client khám phá tài nguyên và gửi các job giả lập. Manager là module phần mềm tự động chịu trách nhiệm kiểm tra yêu cầu, quản lý hàng đợi, phân bổ tài nguyên, ghi nhận kết quả và cập nhật uy tín của Worker. Admin giám sát hoạt động tổng thể.

Dự án lấy cảm hứng từ cơ chế quản lý tài nguyên và lập lịch công việc của các hệ thống HPC như NCI Australia, kết hợp với mô hình GPU marketplace.

### 2. Problem Statement

Việc xây dựng và thử nghiệm một hệ thống phân bổ tài nguyên GPU dùng chung thường đòi hỏi hạ tầng phần cứng, chi phí vận hành và cơ chế điều phối phức tạp.

Dự án giải quyết vấn đề này bằng cách cung cấp môi trường mô phỏng, cho phép kiểm thử các quy trình đăng tài nguyên, gửi job, xếp hàng, cấp phát, theo dõi kết quả và đánh giá độ tin cậy của nhà cung cấp mà không cần GPU thực tế.

### 3. Project Vision

Xây dựng một nền tảng mô phỏng GPU Resource Marketplace có khả năng quản lý nguồn tài nguyên từ nhiều Worker, tiếp nhận yêu cầu tính toán của Client, tự động điều phối các job và ghi nhận kết quả sử dụng.

Hệ thống hướng tới tính minh bạch, nhất quán và khả năng kiểm thử trong toàn bộ vòng đời job.

**Dự án không thực thi tính toán GPU thật, không xử lý thanh toán thật và không sử dụng token có giá trị tài chính.**

### 4. Project Objectives

- **O1 — Resource Sharing:** Cho phép Worker đăng và quản lý tài nguyên GPU giả lập.
- **O2 — Resource Discovery:** Cho phép Client xem, tìm kiếm cơ bản và lựa chọn tài nguyên.
- **O3 — Automated Scheduling:** Manager tự động kiểm tra, xếp hàng và phân bổ GPU cho job.
- **O4 — Job Simulation:** Mô phỏng quá trình thực thi và kết quả hoàn thành hoặc thất bại của job.
- **O5 — Reputation Management:** Ghi nhận lịch sử và đánh giá uy tín Worker dựa trên kết quả giả lập.
- **O6 — System Monitoring:** Cho phép Admin theo dõi trạng thái và hoạt động của hệ thống.

### 5. System Scope — In Scope (MVP)

**5.1. Worker Resource Management**
- Sử dụng tài khoản Worker đã được khởi tạo.
- Đăng tài nguyên GPU giả lập.
- Cấu hình loại GPU, VRAM, số lượng và giá tham khảo.
- Xem và cập nhật thông tin tài nguyên của mình.
- Không được giảm số lượng tài nguyên xuống dưới mức đang được cấp phát.

**5.2. Client Job Management**
- Đăng nhập bằng tài khoản có sẵn.
- Xem danh sách tài nguyên và thông tin Worker.
- Chọn một GPU listing và tạo job với số lượng GPU, thời lượng dự kiến.
- Theo dõi trạng thái và kết quả các job của mình.

**5.3. Automated Manager**
- Kiểm tra tính hợp lệ của yêu cầu.
- Kiểm tra tài nguyên khả dụng.
- Xếp hàng các job theo FIFO trong từng nhóm tài nguyên.
- Cấp phát tài nguyên khi đáp ứng yêu cầu.
- Kích hoạt quá trình mô phỏng thực thi.
- Giải phóng GPU sau khi job hoàn tất hoặc thất bại.
- Ghi nhận kết quả và cập nhật reputation.

**5.4. Job Simulation**
- Mô phỏng thời gian thực thi, không chạy workload AI.
- Hỗ trợ trạng thái QUEUED, RUNNING, COMPLETED và FAILED.
- Cho phép tạo kịch bản thành công hoặc thất bại có thể kiểm thử.
- Lưu lịch sử xử lý job.

**5.5. Reputation Management**
- Lưu số job thành công và thất bại của từng Worker.
- Tính tỷ lệ hoàn thành thành công theo quy tắc minh bạch.
- Cập nhật chỉ số sau khi job có kết quả cuối cùng.
- Hiển thị reputation như một chỉ số được mô phỏng, không phải bằng chứng về hiệu suất phần cứng thực tế.

**5.6. Admin Monitoring**
- Xem danh sách Worker, GPU resources và jobs.
- Theo dõi số lượng job đang chạy, chờ và đã kết thúc.
- Xem lịch sử phân bổ, kết quả và reputation.
- Không thực hiện thao tác điều phối thủ công trong MVP.

### 6. System Scope — Out of Scope

Các chức năng sau không thuộc phạm vi MVP:

- Thực thi AI training/inference trên GPU thật.
- Kết nối và điều khiển GPU phần cứng.
- SSH, container execution hoặc provisioning môi trường tính toán thật.
- Thanh toán, giao dịch tài chính hoặc token có giá trị.
- Blockchain, smart contract hoặc cơ chế thưởng bằng crypto.
- Đăng ký Worker công khai và xác minh nhà cung cấp.
- Scheduling nâng cao như Fair-share và Backfilling.
- Phân bổ một job qua nhiều Worker.
- Đặt trước GPU theo lịch và tự động mở rộng cụm GPU.
- Hệ thống HPC production-grade.

### 7. Core Business Rules

- **BR-01:** Mỗi GPU listing thuộc về một Worker.
- **BR-02:** Một job trong MVP sử dụng tài nguyên của một GPU listing.
- **BR-03:** Số GPU được cấp phát không được vượt quá số lượng khả dụng.
- **BR-04:** Job thiếu tài nguyên được đưa vào hàng đợi.
- **BR-05:** Manager là module tự động, không phải vai trò người dùng.
- **BR-06:** Job hoàn tất hoặc thất bại phải giải phóng tài nguyên đã cấp.
- **BR-07:** Reputation được tính từ lịch sử kết quả mô phỏng theo quy tắc xác định.
- **BR-08:** Giá và chi phí, nếu hiển thị, chỉ mang tính tham khảo hoặc mô phỏng.

### 8. MVP Success Criteria

MVP được xem là đạt yêu cầu khi có thể trình diễn và kiểm thử:

1. Worker đăng thành công một nhóm GPU giả lập.
2. Client lựa chọn tài nguyên và tạo job.
3. Manager tự động xếp hàng và cấp phát GPU.
4. Không xảy ra cấp phát vượt quá công suất, kể cả khi nhiều yêu cầu được gửi đồng thời.
5. Job thay đổi trạng thái và có kết quả mô phỏng.
6. Tài nguyên được giải phóng đúng sau khi job kết thúc.
7. Reputation của Worker được cập nhật dựa trên kết quả job.
8. Admin và Client có thể xem thông tin tương ứng với vai trò của mình.

### 9. Assumptions & Constraints

- GPU và thời gian thực thi đều được mô phỏng bằng phần mềm.
- Các tài khoản Worker, Client và Admin được tạo sẵn trong MVP.
- Scheduling bắt đầu với FIFO và không hỗ trợ thực thi phân tán.
- Thông tin kết quả và reputation chỉ có giá trị trong môi trường mô phỏng.
- Các ràng buộc định lượng về hiệu năng, khả năng mở rộng, bảo mật và lưu trữ sẽ được xác định trong Non-functional Requirements.

### 10. Future Extensions

Các hướng phát triển sau MVP có thể bao gồm đăng ký Worker công khai, quota theo dự án, scheduling nâng cao, cơ chế credit giả lập không thể quy đổi, dashboard phân tích chuyên sâu và tích hợp môi trường tính toán thực tế.